# samples/

Put real correspondence here as `.eml` files for manual runs:

```bash
python -m rotem_agent.cli parse samples\<file>.eml
python -m rotem_agent.cli draft samples\<file>.eml
```

**Nothing in here is committed.** `.gitignore` excludes `samples/*.eml`, because
these files are privileged client material. Do not move a real message into
`tests/`, and do not paste client names, addresses or case details into test
assertions.

The test suite runs against `tests/fixtures/synthetic_thread.eml`, which mirrors
the structure of a real Exchange Online thread with every person and case detail
fabricated. Regenerate it with `python tools/make_fixture.py`.
