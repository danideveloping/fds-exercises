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
        self.is_candidate = False

    def start(self):
        print(f'node {self.id} started')
        threading.Thread(target=self.run).start()

    def run(self):
        while True:
            while buffer[self.id]:
                msg_type, value = buffer[self.id].pop(0)
                if self.working: self.deliver(msg_type,value)
            
            if self.working and self.state == 'follower' and not self.is_candidate and self.voted_for is None:
                if time.time() - self.last_heartbeat > self.election_timeout:
                    self.start_election()
            
            if self.working and self.state == 'leader':
                if time.time() - self.last_heartbeat >= self.heartbeat_interval:
                    self.broadcast(HEARTBEAT, self.id)
                    self.last_heartbeat = time.time()
            
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
    
    def recover(self):
        if not self.working:
            buffer[self.id] = []
            self.working = True

    def start_election(self):
        if self.state != 'follower' or self.is_candidate or self.voted_for is not None:
            return
        
        delay = random.uniform(1.0, 3.0)
        print(f'node {self.id} is starting an election.')
        
        self.is_candidate = True
        
        threading.Thread(target=self._delayed_election, args=(delay,)).start()
    
    def _delayed_election(self, delay):
        time.sleep(delay)
        
        if self.state == 'follower' and self.is_candidate and self.voted_for is None:
            self.become_candidate()
    
    def become_candidate(self):
        if self.state != 'follower':
            return
            
        self.state = 'candidate'
        self.votes_received = 1
        self.voted_for = self.id
        self.election_start_time = time.time()
        self.is_candidate = True
        
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
        
        self.is_candidate = False

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
            self.is_candidate = False
            print(f'node {self.id} got a heartbeat and followed node {leader_id} as leader')
        elif self.state == 'follower':
            self.is_candidate = False
            self.voted_for = None
            self.votes_received = 0
    
    def handle_candidacy(self, candidate_id):
        if self.voted_for is None and self.state == 'follower':
            self.voted_for = candidate_id
            self.broadcast(VOTE, {'voter': self.id, 'candidate': candidate_id})
            print(f'node {self.id} voted to node {candidate_id}')
        
        if self.state == 'follower' and self.is_candidate:
            self.is_candidate = False
    
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
    
    while not election_finished:
        time.sleep(0.1)
    
    print('\nFinal state:')
    for node in nodes:
        print(f'node {node.id}: {node.state}')
    
    print('\nElection completed. Program exiting.')

