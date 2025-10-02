# Test Suite Notes

## Async API deadline checks

The tests in `tests/routers/test_request_deadlines.py` exercise the asynchronous request
path for `/imports/free` and `/sync`. They rely on the shared
`async_client_with_deadline` fixture to ensure database interactions stay off the event
loop and complete within the configured deadline. Include them in your regular workflow
by running:

```bash
pytest tests/routers/test_request_deadlines.py
```

They also run automatically when executing the full test suite.
