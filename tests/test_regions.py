from job_radar.regions import classify_region


def test_classify_india():
    assert classify_region("Bengaluru, India") == "india"
    assert classify_region("Remote - India") == "india"
    assert classify_region("", hint="india") == "india"


def test_classify_germany():
    assert classify_region("Berlin, Germany") == "germany"
    assert classify_region("München") == "germany"
    assert classify_region("", hint="germany") == "germany"


def test_classify_other():
    assert classify_region("Toronto, Canada") == "other"
    assert classify_region("") == "other"
