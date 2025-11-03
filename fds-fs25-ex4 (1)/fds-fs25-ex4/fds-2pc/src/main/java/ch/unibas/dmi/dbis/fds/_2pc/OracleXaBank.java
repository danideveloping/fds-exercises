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

            // 2PC Phase 1: Prepare both transactions
            // PRESUMED ABORT: If coordinator crashes after prepare, banks would timeout and abort.
            // Coordinator would assume abort on recovery (presumed abort). XA doesn't support this
            // natively - would need custom timeout logic in banks.
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

            // 2PC Phase 2: Commit both transactions
            // TRANSFER OF COORDINATION: After prepare, coordinator could transfer responsibility
            // to FROM_BANK. FROM_BANK would then send commit to TO_BANK and commit itself.
            // This eliminates single point of failure. XA doesn't support this - would need
            // custom protocol for bank-to-bank communication.
            this.commitTransaction( fromXid, false );
            TO_BANK.commitTransaction( toXid, false );

        } catch ( SQLException | XAException | IllegalArgumentException e ) {
            LOG.log( java.util.logging.Level.SEVERE, "Error during transfer, rolling back transaction", e );
            
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
                LOG.log( java.util.logging.Level.SEVERE, "Error during rollback", rollbackEx );
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
