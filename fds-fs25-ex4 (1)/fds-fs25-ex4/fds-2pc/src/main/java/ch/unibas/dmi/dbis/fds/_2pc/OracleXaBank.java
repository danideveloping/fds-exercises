package ch.unibas.dmi.dbis.fds._2pc;


import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import javax.transaction.xa.XAException;
import javax.transaction.xa.XAResource;
import javax.transaction.xa.Xid;


/**
 * Check the XA stuff here --> https://docs.oracle.com/cd/B14117_01/java.101/b10979/xadistra.htm
 *
 * @author Alexander Stiemer (alexander.stiemer at unibas.ch)
 */
public class OracleXaBank extends AbstractOracleXaBank {


    public OracleXaBank( final String BIC, final String jdbcConnectionString, final String dbmsUsername, final String dbmsPassword ) throws SQLException {
        super( BIC, jdbcConnectionString, dbmsUsername, dbmsPassword );
    }


    @Override
    public float getBalance( final String iban ) throws SQLException {
        try ( Connection connection = this.getXaConnection().getConnection() ) {
            final String query = "SELECT balance FROM account WHERE iban = ?";
            try ( PreparedStatement statement = connection.prepareStatement( query ) ) {
                statement.setString( 1, iban );
                try ( ResultSet resultSet = statement.executeQuery() ) {
                    if ( !resultSet.next() ) {
                        throw new SQLException( "Account with IBAN " + iban + " does not exist" );
                    }
                    return resultSet.getFloat( "balance" );
                }
            }
        }
    }


    /**
     * Executes a money transfer between two banks using 2PC protocol.
     * 
     * 2PC VARIANT ANALYSIS FOR BANKING SCENARIO:
     * 
     * 1. PRESUMED ABORT 2PC:
     *    - WOULD MAKE SENSE: Yes, because it allows automatic recovery from coordinator
     *      crashes. Banks would timeout and abort prepared transactions, preventing indefinite
     *      locks on customer accounts. This is critical for banking where account locks
     *      could block legitimate transactions.
     *    - WHY XA DOESN'T SUPPORT IT: XA protocol requires explicit commit/abort messages.
     *      Banks cannot autonomously timeout and abort - they must wait for coordinator.
     *      Would need custom timeout logic and crash detection mechanism.
     *    - IMPLEMENTATION REQUIRED: Custom timeout handlers in banks, coordinator heartbeat
     *      mechanism, and state recovery protocol.
     * 
     * 2. TRANSFER OF COORDINATION 2PC:
     *    - WOULD MAKE SENSE: Yes, because it eliminates the single point of failure.
     *      If the coordinator (this Java app) crashes after prepare, FROM_BANK could
     *      still complete the transaction, ensuring customer transfers aren't blocked.
     *    - WHY XA DOESN'T SUPPORT IT: XA assumes a single transaction manager (coordinator).
     *      Banks cannot directly communicate with each other to coordinate commits.
     *      Would need custom bank-to-bank communication protocol.
     *    - IMPLEMENTATION REQUIRED: Direct communication channel between banks, protocol
     *      for coordination transfer, and handling of cascading coordinator failures.
     * 
     * CONCLUSION: Both variants would improve fault tolerance in banking, but XA's
     * architecture prevents their implementation without custom extensions beyond the
     * standard XA API.
     */
    @Override
    public void transfer( final AbstractOracleXaBank TO_BANK, final String ibanFrom, final String ibanTo, final float value ) {
        if ( value <= 0 ) {
            throw new IllegalArgumentException( "Transfer value must be positive" );
        }

        Xid globalXid = null;
        Xid fromXid = null;
        Xid toXid = null;
        boolean fromBranchStarted = false;
        boolean toBranchStarted = false;
        boolean fromBranchEnded = false;
        boolean toBranchEnded = false;
        boolean fromPrepared = false;
        boolean toPrepared = false;

        try {
            // Start both transaction branches before doing any work
            fromXid = this.startTransaction();
            fromBranchStarted = true;
            
            final byte[] globalTransactionIdBytes = fromXid.getGlobalTransactionId();
            globalXid = fromXid;

            // Use TMNOFLAGS for second branch because it's on a different server
            toXid = TO_BANK.getXid( globalTransactionIdBytes );
            TO_BANK.getXaResource().start( toXid, XAResource.TMNOFLAGS );
            toBranchStarted = true;

            // Execute withdraw
            try ( Connection connection = this.getXaConnection().getConnection() ) {
                final String checkQuery = "SELECT balance FROM account WHERE iban = ? FOR UPDATE";
                try ( PreparedStatement checkStatement = connection.prepareStatement( checkQuery ) ) {
                    checkStatement.setString( 1, ibanFrom );
                    try ( ResultSet resultSet = checkStatement.executeQuery() ) {
                        if ( !resultSet.next() ) {
                            throw new SQLException( "Account with IBAN " + ibanFrom + " does not exist" );
                        }
                        float currentBalance = resultSet.getFloat( "balance" );
                        if ( currentBalance < value ) {
                            throw new SQLException( "Insufficient balance in account " + ibanFrom + ". Current balance: " + currentBalance + ", required: " + value );
                        }
                    }
                }

                final String withdrawQuery = "UPDATE account SET balance = balance - ? WHERE iban = ?";
                try ( PreparedStatement withdrawStatement = connection.prepareStatement( withdrawQuery ) ) {
                    withdrawStatement.setFloat( 1, value );
                    withdrawStatement.setString( 2, ibanFrom );
                    int rowsUpdated = withdrawStatement.executeUpdate();
                    if ( rowsUpdated == 0 ) {
                        throw new SQLException( "Failed to withdraw from account " + ibanFrom );
                    }
                }
            }

            // Execute deposit
            try ( Connection connection = TO_BANK.getXaConnection().getConnection() ) {
                final String checkQuery = "SELECT balance FROM account WHERE iban = ? FOR UPDATE";
                try ( PreparedStatement checkStatement = connection.prepareStatement( checkQuery ) ) {
                    checkStatement.setString( 1, ibanTo );
                    try ( ResultSet resultSet = checkStatement.executeQuery() ) {
                        if ( !resultSet.next() ) {
                            throw new SQLException( "Account with IBAN " + ibanTo + " does not exist" );
                        }
                        float currentBalance = resultSet.getFloat( "balance" );
                        if ( currentBalance + value > 15000 ) {
                            throw new SQLException( "Account " + ibanTo + " would exceed maximum capacity. Current balance: " + currentBalance + ", transfer: " + value + ", maximum: 15000" );
                        }
                    }
                }

                final String depositQuery = "UPDATE account SET balance = balance + ? WHERE iban = ?";
                try ( PreparedStatement depositStatement = connection.prepareStatement( depositQuery ) ) {
                    depositStatement.setFloat( 1, value );
                    depositStatement.setString( 2, ibanTo );
                    int rowsUpdated = depositStatement.executeUpdate();
                    if ( rowsUpdated == 0 ) {
                        throw new SQLException( "Failed to deposit to account " + ibanTo );
                    }
                }
            }

            // End both branches
            this.endTransaction( fromXid, false );
            fromBranchEnded = true;
            TO_BANK.endTransaction( toXid, false );
            toBranchEnded = true;

            // ============================================================================
            // 2PC VARIANT ANALYSIS:
            // 
            // PRESUMED ABORT 2PC: This variant makes sense for banking because it reduces
            // uncertainty after coordinator failures. If the coordinator (this Java application)
            // crashes after sending prepare but before sending commit/abort, banks would:
            // 1. Wait for a timeout period
            // 2. If no commit/abort message arrives, they would abort (rollback) the transaction
            // 3. On recovery, the coordinator would assume all transactions were aborted
            //    (presumed abort) and would not need to query banks about their state.
            // 
            // BENEFIT: Faster recovery - no need to contact banks to determine state.
            // DRAWBACK: XA doesn't support this natively - would need custom timeout logic
            // in both banks and a way to detect coordinator crashes.
            // ============================================================================
            // 2PC Phase 1: Prepare both transactions
            // PRESUMED ABORT SCENARIO: If coordinator crashes here (after prepare completes
            // but before commit), both banks would have prepared transactions waiting.
            // With Presumed Abort: Banks would timeout (e.g., after 30 seconds), automatically
            // rollback their prepared transactions, and release locks. When coordinator
            // recovers, it assumes all pending transactions were aborted (no state query needed).
            // Current implementation: Banks would keep locks indefinitely until coordinator
            // recovers and sends commit/abort, or manual intervention.
            int fromPrepareResult = this.prepareTransaction( fromXid );
            if ( fromPrepareResult != XAResource.XA_OK && fromPrepareResult != XAResource.XA_RDONLY ) {
                throw new XAException( "Prepare failed for FROM_BANK transaction" );
            }
            fromPrepared = true;

            int toPrepareResult = TO_BANK.prepareTransaction( toXid );
            if ( toPrepareResult != XAResource.XA_OK && toPrepareResult != XAResource.XA_RDONLY ) {
                throw new XAException( "Prepare failed for TO_BANK transaction" );
            }
            toPrepared = true;

            // ============================================================================
            // TRANSFER OF COORDINATION 2PC: This variant makes sense for banking because
            // it eliminates the single point of failure (the coordinator). After prepare
            // completes successfully, the coordinator could transfer responsibility to
            // FROM_BANK, making it the new coordinator. FROM_BANK would then:
            // 1. Send commit message to TO_BANK
            // 2. Wait for TO_BANK's acknowledgment
            // 3. Commit its own transaction
            // 4. Notify the original coordinator (if it's still alive)
            // 
            // BENEFIT: If original coordinator crashes after prepare, FROM_BANK can still
            // complete the transaction. No single point of failure.
            // DRAWBACK: XA doesn't support this - would need custom bank-to-bank communication
            // protocol. Also adds complexity (what if FROM_BANK crashes after becoming coordinator?).
            // ============================================================================
            // 2PC Phase 2: Commit both transactions
            // TRANSFER OF COORDINATION SCENARIO: At this point, if using Transfer of
            // Coordination, the coordinator (this code) would:
            // 1. Send "transfer coordination" message to FROM_BANK with TO_BANK's address
            // 2. FROM_BANK becomes new coordinator
            // 3. FROM_BANK sends commit to TO_BANK and waits for acknowledgment
            // 4. FROM_BANK commits its own transaction
            // 5. If original coordinator recovers, FROM_BANK reports completion
            // 
            // Current implementation: Coordinator directly commits both branches.
            // If coordinator crashes here, both banks would be stuck in prepared state
            // until manual intervention or recovery.
            this.commitTransaction( fromXid, false );
            TO_BANK.commitTransaction( toXid, false );

        } catch ( SQLException | XAException | IllegalArgumentException e ) {
            // Only log the message, not full stack trace for cleaner test output
            LOG.log( java.util.logging.Level.INFO, "Transfer failed: " + e.getMessage() + " - Rolling back transaction" );
            
            try {
                if ( fromPrepared && fromXid != null ) {
                    this.rollbackTransaction( fromXid );
                } else if ( fromBranchEnded && fromXid != null ) {
                    this.rollbackTransaction( fromXid );
                } else if ( fromBranchStarted && fromXid != null ) {
                    try {
                        this.endTransaction( fromXid, true );
                    } catch ( XAException ex ) {
                        // ignore
                    }
                    this.rollbackTransaction( fromXid );
                }

                if ( toPrepared && toXid != null ) {
                    TO_BANK.rollbackTransaction( toXid );
                } else if ( toBranchEnded && toXid != null ) {
                    TO_BANK.rollbackTransaction( toXid );
                } else if ( toBranchStarted && toXid != null ) {
                    try {
                        TO_BANK.endTransaction( toXid, true );
                    } catch ( XAException ex ) {
                        // ignore
                    }
                    TO_BANK.rollbackTransaction( toXid );
                }
            } catch ( XAException rollbackEx ) {
                LOG.log( java.util.logging.Level.WARNING, "Rollback error: " + rollbackEx.getMessage() );
            }

            if ( e instanceof RuntimeException ) {
                throw ( RuntimeException ) e;
            } else if ( e instanceof SQLException ) {
                throw new RuntimeException( "SQL error during transfer: " + e.getMessage(), e );
            } else if ( e instanceof XAException ) {
                throw new RuntimeException( "XA error during transfer: " + e.getMessage(), e );
            } else {
                throw new RuntimeException( "Error during transfer: " + e.getMessage(), e );
            }
        }
    }
}
