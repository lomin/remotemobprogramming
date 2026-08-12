from remotemobprogramming import greet


def test_greet_uses_the_given_name():
    assert greet("mob") == "Hello, mob!"


# Red-green-refactor: write the next failing test here, watch it go red in the
# watcher, then make it pass. Delete this file once the real kata starts.
