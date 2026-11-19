# Answer 1 from the orchestrator

Yes, a harness fault: step_done does not see the harness's own handback commit before the catch-up. Use the other harness door: run('git', 'commit', {files: ['orch-probe/hello.py'], message: 'Add a module docstring naming AC1 and AC2'}), then step_done (it adopts that commit), push, and hand back again. Change nothing else.
