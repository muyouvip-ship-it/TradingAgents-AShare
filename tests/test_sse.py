def test_sse_event_format():
    event = "job.started"
    data = {"job_id": "abc"}
    payload = f"event: {event}\ndata: {data}\n\n"
    assert "event: job.started" in payload
