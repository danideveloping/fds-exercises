import os
import time
import threading
import random

nodes = []
buffer = {}
election_finished = False

CANDIDACY = 'candidacy'
VOTE = 'vote'
HEARTBEAT = 'heartbeat'

class Node:
    def __init__(self,id):
        buffer[id] = []
        self.id = id
        self.working = True
        self.state = 'follower'
        self.votes_received = 0
        self.voted_for = None
        self.last_heartbeat = time.time()
        self.election_timeout = 1.0
        self.heartbeat_interval = 0.5
        self.election_start_time = 0
        self.is_waiting_for_election = False
        self.wait_start_time = 0
        self.candidacy_received_during_wait = False

    def start(self):
        print(f'node {self.id} started')
        threading.Thread(target=self.run).start()

    def run(self):
        while True:
            while buffer[self.id]:
                msg_type, value = buffer[self.id].pop(0)
                if self.working: self.deliver(msg_type,value)
            
            # Check if follower needs to start election (no heartbeat received)
            if self.working and self.state == 'follower' and not self.is_waiting_for_election and self.voted_for is None:
                if time.time() - self.last_heartbeat > self.election_timeout:
                    self.start_election()
            
            # Leader sends heartbeats
            if self.working and self.state == 'leader':
                if time.time() - self.last_heartbeat >= self.heartbeat_interval:
                    self.broadcast(HEARTBEAT, self.id)
                    self.last_heartbeat = time.time()
            
            # Candidate counts votes after vote collection period
            if self.working and self.state == 'candidate':
                if time.time() - self.election_start_time > 2.0:
                    self.count_votes()
            
            time.sleep(0.1)

    def broadcast(self, msg_type, value):
        if self.working:
            for node in nodes:
                buffer[node.id].append((msg_type,value))
    
    def crash(self):
        if self.working:
            self.working = False
            buffer[self.id] = []
            # If this was the leader, reset election state for new election
            if self.state == 'leader':
                global election_finished
                election_finished = False
    
    def recover(self):
        if not self.working:
            buffer[self.id] = []
            self.working = True
            # Reset state to follower when recovering
            self.state = 'follower'
            self.votes_received = 0
            self.voted_for = None
            self.is_waiting_for_election = False
            self.candidacy_received_during_wait = False
            # Reset heartbeat timer to give time to receive heartbeats from existing leader
            self.last_heartbeat = time.time()

    def _has_leader(self):
        """Check if there's already a working leader"""
        for node in nodes:
            if node.working and node.state == 'leader':
                return True
        return False

    def start_election(self):
        if self.state != 'follower' or self.is_waiting_for_election or self.voted_for is not None:
            return
        
        # Don't start election if there's already a leader
        if self._has_leader():
            return
        
        print(f'node {self.id} is starting an election.')
        
        # Start waiting period with random delay (1-3 seconds)
        delay = random.uniform(1.0, 3.0)
        self.is_waiting_for_election = True
        self.wait_start_time = time.time()
        self.candidacy_received_during_wait = False
        
        # Schedule the candidacy announcement after the delay
        threading.Thread(target=self._delayed_candidacy, args=(delay,)).start()
    
    def _delayed_candidacy(self, delay):
        time.sleep(delay)
        
        # Check if we should still become a candidate
        if (self.state == 'follower' and 
            self.is_waiting_for_election and 
            not self.candidacy_received_during_wait):
            self.become_candidate()
    
    def _has_received_candidacy_during_wait(self):
        return self.candidacy_received_during_wait
    
    def become_candidate(self):
        if self.state != 'follower' or not self.is_waiting_for_election:
            return
            
        self.state = 'candidate'
        self.votes_received = 1  # Vote for self
        self.voted_for = self.id
        self.election_start_time = time.time()
        self.is_waiting_for_election = False
        
        self.broadcast(CANDIDACY, self.id)
        print(f'node {self.id} voted to node {self.id}')
    
    def count_votes(self):
        global election_finished
        
        if self.state != 'candidate':
            return
            
        total_nodes = len([n for n in nodes if n.working])
        majority = total_nodes // 2 + 1
        
        print(f'node {self.id} election results: {self.votes_received}/{total_nodes} votes (need {majority} for majority)')
        
        if self.votes_received >= majority:
            self.state = 'leader'
            print(f'node {self.id} detected node {self.id} as leader')
            self.last_heartbeat = time.time()
            election_finished = True
        else:
            self.state = 'follower'
            self.votes_received = 0
            self.voted_for = None
            self.is_waiting_for_election = False

    def deliver(self, msg_type, value):
        if not self.working:
            return
            
        if msg_type == HEARTBEAT:
            self.handle_heartbeat(value)
        elif msg_type == CANDIDACY:
            self.handle_candidacy(value)
        elif msg_type == VOTE:
            self.handle_vote(value)
    
    def handle_heartbeat(self, leader_id):
        self.last_heartbeat = time.time()
        
        if self.state == 'candidate':
            self.state = 'follower'
            self.votes_received = 0
            self.voted_for = None
            self.is_waiting_for_election = False
            print(f'node {self.id} got a heartbeat and followed node {leader_id} as leader')
        elif self.state == 'follower':
            self.is_waiting_for_election = False
            self.voted_for = None
            self.votes_received = 0
    
    def handle_candidacy(self, candidate_id):
        # If we're waiting for election and receive a candidacy, resign our candidacy
        if self.state == 'follower' and self.is_waiting_for_election:
            self.is_waiting_for_election = False
            self.candidacy_received_during_wait = True
            print(f'node {self.id} resigns candidacy due to received candidacy from node {candidate_id}')
        
        # Vote for the candidate if we haven't voted yet
        if self.voted_for is None and self.state == 'follower':
            self.voted_for = candidate_id
            self.broadcast(VOTE, {'voter': self.id, 'candidate': candidate_id})
            print(f'node {self.id} voted to node {candidate_id}')
    
    def handle_vote(self, vote_data):
        voter_id = vote_data['voter']
        candidate_id = vote_data['candidate']
        
        if self.state == 'candidate' and candidate_id == self.id:
            self.votes_received += 1

def initialize(N):
    global nodes
    nodes = [Node(i) for i in range(N)]
    for node in nodes:
        node.start()

if __name__ == "__main__":
    N = 3
    initialize(N)
    print('actions: state, crash, recover')
    
    # Wait for initial election to complete
    while not election_finished:
        time.sleep(0.1)
    
    print('\nInitial election completed.')
    print('actions: state, crash, recover')
    
    # Continue running for interactive testing
    while True:
        try:
            command = input().strip().lower()
            if command == 'state':
                print('\nCurrent state:')
                for node in nodes:
                    if node.working:
                        print(f'node {node.id}: {node.state}')
                    else:
                        print(f'node {node.id}: crashed')
            elif command.startswith('crash'):
                try:
                    node_id = int(command.split()[1])
                    if 0 <= node_id < len(nodes):
                        nodes[node_id].crash()
                        print(f'node {node_id} crashed')
                    else:
                        print(f'Invalid node ID: {node_id}')
                except (IndexError, ValueError):
                    print('Usage: crash <node_id>')
            elif command.startswith('recover'):
                try:
                    node_id = int(command.split()[1])
                    if 0 <= node_id < len(nodes):
                        nodes[node_id].recover()
                        print(f'node {node_id} recovered')
                    else:
                        print(f'Invalid node ID: {node_id}')
                except (IndexError, ValueError):
                    print('Usage: recover <node_id>')
            elif command == 'quit' or command == 'exit':
                break
            else:
                print('Unknown command. Available: state, crash <node_id>, recover <node_id>, quit')
        except KeyboardInterrupt:
            break
        except EOFError:
            break
    
    print('\nProgram exiting.')

