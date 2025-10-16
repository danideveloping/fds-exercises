
class CLS:
    def __init__(self):
        self.A = {}
    
    def add(self, element):
        if element not in self.A:
            self.A[element] = 1
        else:
            if self.A[element] % 2 == 0:
                self.A[element] += 1
    
    def remove(self, element):
        if element in self.A and self.A[element] % 2 == 1:
            self.A[element] += 1
    
    def contains(self, element):
        return element in self.A and self.A[element] % 2 == 1
    
    def mutual_sync(self, other_lists):
        for other_list in other_lists:
            self.A = self.merge(self.A, other_list.A)
            other_list.A = self.merge(other_list.A, self.A)
    
    def merge(self, S, T):
        U = {}
        all_elements = set(S.keys()) | set(T.keys())
        
        for element in all_elements:
            s_value = S.get(element, 0)
            t_value = T.get(element, 0)
            U[element] = max(s_value, t_value)
        
        return U
    
    def __str__(self):
        return str(self.A)

if __name__ == "__main__":
    alice_list = CLS()
    bob_list = CLS()
    
    alice_list.add('Milk')
    alice_list.add('Potato')
    alice_list.add('Eggs')
    
    bob_list.add('Sausage')
    bob_list.add('Mustard')
    bob_list.add('Coke')
    bob_list.add('Potato')
    
    bob_list.mutual_sync([alice_list])
    
    alice_list.remove('Sausage')
    alice_list.add('Tofu')
    alice_list.remove('Potato')
    
    alice_list.mutual_sync([bob_list])
    
    print("Bob's list contains 'Potato'?", bob_list.contains('Potato'))
    print("Alice's list contains 'Potato'?", alice_list.contains('Potato'))
    
    print("\nFinal states:")
    print("Alice's list:", alice_list)
    print("Bob's list:", bob_list)
