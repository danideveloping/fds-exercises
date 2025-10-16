import json   
import os
from typing import Dict, List, Tuple, Set


BranchIndex = Dict[str, int]
CommitToBranch = Dict[str, str]
CommitToParents = Dict[str, List[str]]
Clock = List[int]
CommitToClock = Dict[str, Clock]


def load_repo(json_path: str) -> Tuple[BranchIndex, CommitToBranch, CommitToParents]:
    data = json.load(open(json_path, 'r'))
    branch_to_index: BranchIndex = {}
    commit_to_branch: CommitToBranch = {}
    commit_to_parents: CommitToParents = {}

    for idx, branch in enumerate(data.keys()):
        branch_to_index[branch] = idx
        for commit, parents in data[branch].items():
            commit_to_branch[commit] = branch
            commit_to_parents[commit] = list(parents)

    return branch_to_index, commit_to_branch, commit_to_parents


def elementwise_max(vectors: List[Clock]) -> Clock:
    if not vectors:
        return []
    length = len(vectors[0])
    result = [0] * length
    for vec in vectors:
        for i in range(length):
            if vec[i] > result[i]:
                result[i] = vec[i]
    return result


def compute_vector_clocks(
    branch_to_index: BranchIndex,
    commit_to_branch: CommitToBranch,
    commit_to_parents: CommitToParents,
) -> CommitToClock:
    num_processes = len(branch_to_index)
    memo: CommitToClock = {}

    def clock_of(commit: str) -> Clock:
        if commit in memo:
            return memo[commit]
        branch = commit_to_branch[commit]
        proc_index = branch_to_index[branch]
        parents = commit_to_parents.get(commit, [])
        if not parents:
            v = [0] * num_processes
            v[proc_index] += 1
            memo[commit] = v
            return v
        parent_clocks = [clock_of(p) for p in parents]
        v = elementwise_max(parent_clocks)
        if len(v) == 0:
            v = [0] * num_processes
        v[proc_index] += 1
        memo[commit] = v
        return v

    for commit in commit_to_branch.keys():
        clock_of(commit)

    return memo


def causally_precedes(a: Clock, b: Clock) -> bool:
    if len(a) != len(b):
        return False
    le_all = True
    lt_any = False
    for i in range(len(a)):
        if a[i] > b[i]:
            le_all = False
            break
        if a[i] < b[i]:
            lt_any = True
    return le_all and lt_any


def build_causal_edges(commits: List[str], clocks: CommitToClock) -> Set[Tuple[str, str]]:
    edges: Set[Tuple[str, str]] = set()
    for i in range(len(commits)):
        u = commits[i]
        for j in range(len(commits)):
            if i == j:
                continue
            v = commits[j]
            if causally_precedes(clocks[u], clocks[v]):
                edges.add((u, v))
    return edges


def transitive_reduction(commits: List[str], edges: Set[Tuple[str, str]], clocks: CommitToClock) -> Set[Tuple[str, str]]:
    minimal = set(edges)
    for (u, v) in list(edges):
        for w in commits:
            if w == u or w == v:
                continue
            if causally_precedes(clocks[u], clocks[w]) and causally_precedes(clocks[w], clocks[v]):
                if (u, v) in minimal:
                    minimal.remove((u, v))
                break
    return minimal


def write_clocks_json(clocks: CommitToClock, out_path: str) -> None:
    ordered = {k: clocks[k] for k in sorted(clocks.keys())}
    with open(out_path, 'w') as f:
        json.dump(ordered, f, indent=2)


def write_dot(commits: List[str], edges: Set[Tuple[str, str]], clocks: CommitToClock, out_path: str) -> None:
    with open(out_path, 'w') as f:
        f.write('digraph G {\n')
        for c in commits:
            label = f"{c}\\n{clocks[c]}"
            f.write(f'  "{c}" [label="{label}"];\n')
        for (u, v) in edges:
            f.write(f'  "{u}" -> "{v}";\n')
        f.write('}\n')


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(here, 'example.json')
    branch_to_index, commit_to_branch, commit_to_parents = load_repo(json_path)

    clocks = compute_vector_clocks(branch_to_index, commit_to_branch, commit_to_parents)
    commits = sorted(clocks.keys())

    edges_full = build_causal_edges(commits, clocks)
    edges_min = transitive_reduction(commits, edges_full, clocks)

    write_clocks_json(clocks, os.path.join(here, 'vector_clocks.json'))
    write_dot(commits, edges_full, clocks, os.path.join(here, 'causal_full.dot'))
    write_dot(commits, edges_min, clocks, os.path.join(here, 'causal_min.dot'))

    print('Branches:', list(branch_to_index.keys()))
    print('Processes:', len(branch_to_index))
    print('Commits:', len(commits))
    print('Vector clocks written to vector_clocks.json')
    print('Full causal graph written to causal_full.dot')
    print('Minimal causal graph written to causal_min.dot')


if __name__ == '__main__':
    main()