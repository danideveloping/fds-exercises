import os
import time
import threading
import random

nodes = []
buffer = {} # items are in the form 'node_id': [(msg_type, value)]

# Message types
CANDIDACY = 'candidacy'
VOTE = 'vote'
HEARTBEAT = 'heartbeat'

class Node:
    def __init__(self,id):
        buffer[id] = []
        self.id = id
        self.working = True
        self.state = 'follower'  # Start as follower
        self.votes_received = 0
        self.voted_for = None
        self.last_heartbeat = time.time()
        self.election_timeout = 1.0  # 1 second timeout for heartbeat detection
        self.heartbeat_interval = 0.5  # Send heartbeat every 0.5 seconds
        self.election_start_time = 0
        self.is_candidate = False

    def start(self):
        print(f'node {self.id} started')
        threading.Thread(target=self.run).start()

    def run(self):
        while True:
            # Process incoming messages
            while buffer[self.id]:
                msg_type, value = buffer[self.id].pop(0)
                if self.working: self.deliver(msg_type,value)
            
            # Check for heartbeat timeout and start election if needed
            if self.working and self.state == 'follower':
                if time.time() - self.last_heartbeat > self.election_timeout:
                    self.start_election()
            
            # Leader sends heartbeats
            if self.working and self.state == 'leader':
                if time.time() - self.last_heartbeat >= self.heartbeat_interval:
                    self.broadcast(HEARTBEAT, self.id)
                    self.last_heartbeat = time.time()
            
            # Check election timeout for candidates
            if self.working and self.state == 'candidate':
                if time.time() - self.election_start_time > 2.0:  # 2 second vote collection period
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
    
    def recover(self):
        if not self.working:
            buffer[self.id] = []
            self.working = True

    def start_election(self):
        """Start election process with random delay"""
        if self.state != 'follower':
            return
        
        # Random delay between 1-3 seconds
        delay = random.uniform(1.0, 3.0)
        print(f'node {self.id} is starting an election.')
        
        # Start a separate thread for the delayed election
        threading.Thread(target=self._delayed_election, args=(delay,)).start()
    
    def _delayed_election(self, delay):
        """Execute election after delay, checking for other candidacies"""
        time.sleep(delay)
        
        # Check if we received any candidacy messages during the delay
        if self.state == 'follower' and not self.is_candidate:
            self.become_candidate()
    
    def become_candidate(self):
        """Become a candidate and start vote collection"""
        if self.state != 'follower':
            return
            
        self.state = 'candidate'
        self.votes_received = 1  # Vote for self
        self.voted_for = self.id
        self.election_start_time = time.time()
        self.is_candidate = True
        
        # Broadcast candidacy
        self.broadcast(CANDIDACY, self.id)
        print(f'node {self.id} voted to node {self.id}')
    
    def count_votes(self):
        """Count votes and determine if elected"""
        if self.state != 'candidate':
            return
            
        total_nodes = len([n for n in nodes if n.working])
        majority = total_nodes // 2 + 1
        
        if self.votes_received >= majority:
            self.state = 'leader'
            print(f'node {self.id} detected node {self.id} as leader')
            self.last_heartbeat = time.time()
        else:
            # Election failed, return to follower
            self.state = 'follower'
            self.votes_received = 0
            self.voted_for = None
        
        self.is_candidate = False

    def deliver(self, msg_type, value):
        """Handle incoming messages"""
        if not self.working:
            return
            
        if msg_type == HEARTBEAT:
            self.handle_heartbeat(value)
        elif msg_type == CANDIDACY:
            self.handle_candidacy(value)
        elif msg_type == VOTE:
            self.handle_vote(value)
    
    def handle_heartbeat(self, leader_id):
        """Handle heartbeat message from leader"""
        self.last_heartbeat = time.time()
        
        # If we're a candidate or follower, accept this leader
        if self.state in ['candidate', 'follower']:
            self.state = 'follower'
            self.votes_received = 0
            self.voted_for = None
            self.is_candidate = False
            print(f'node {self.id} got a heartbeat and followed node {leader_id} as leader')
    
    def handle_candidacy(self, candidate_id):
        """Handle candidacy message from another node"""
        # If we haven't voted yet, vote for this candidate
        if self.voted_for is None and self.state == 'follower':
            self.voted_for = candidate_id
            self.broadcast(VOTE, {'voter': self.id, 'candidate': candidate_id})
            print(f'node {self.id} voted to node {candidate_id}')
        
        # If we're waiting to become a candidate, cancel our candidacy
        if self.state == 'follower' and self.is_candidate:
            self.is_candidate = False
    
    def handle_vote(self, vote_data):
        """Handle vote message"""
        if self.state == 'candidate' and vote_data['candidate'] == self.id:
            self.votes_received += 1

def initialize(N):
    global nodes
    nodes = [Node(i) for i in range(N)]
    for node in nodes:
        node.start()

if __name__ == "__main__":
    os.system('clear')
    N = 3
    initialize(N)
    print('actions: state, crash, recover')
    while True:
        act = input('\t$ ')
        if act == 'crash' : 
            id = int(input('\tid > '))
            if 0<= id and id<N: nodes[id].crash()
        elif act == 'recover' : 
            id = int(input('\tid > '))
            if 0<= id and id<N: nodes[id].recover()
        elif act == 'state':
            for node in nodes:
                print(f'\t\tnode {node.id}: {node.state}')

