from tg_netdisk.services.progress import UploadProgress


def test_eta_waits_for_recent_stable_samples():
    clock = [0.0]
    tracker = UploadProgress([1000], clock=lambda: clock[0])
    assert tracker.initial()["eta_seconds"] is None
    assert tracker.update(0, 0, 1000)["eta_seconds"] is None
    clock[0] = 1
    assert tracker.update(0, 100, 1000)["eta_seconds"] is None
    clock[0] = 2
    progress = tracker.update(0, 200, 1000)
    assert progress["speed"] == 100
    assert progress["eta_seconds"] == 8


def test_eta_drops_stalled_samples_and_resets_on_regression():
    clock = [0.0]
    tracker = UploadProgress([1000], clock=lambda: clock[0])
    for timestamp in range(3):
        clock[0] = timestamp
        tracker.update(0, timestamp * 100, 1000)
    clock[0] = 20
    stalled = tracker.update(0, 200, 1000)
    assert stalled["speed"] == 0 and stalled["eta_seconds"] is None
    clock[0] = 21
    assert tracker.update(0, 0, 1000)["eta_seconds"] is None
    assert UploadProgress([1000]).initial()["sent"] == 0


def test_album_progress_uses_actual_photo_sizes_and_never_exceeds_total():
    tracker = UploadProgress([1000, 1000])
    photo = tracker.update(0, 100, 100)
    assert photo["sent"] == 100 and photo["total"] == 1100
    second = tracker.update(1, 50, 200)
    assert second["sent"] == 150 and second["total"] == 300
    complete = tracker.update(1, 250, 200)
    assert complete["sent"] == complete["total"] == 300
    assert complete["eta_seconds"] is None


def test_eta_uses_recent_speed_instead_of_all_time_average():
    clock = [0.0]
    tracker = UploadProgress([1000], clock=lambda: clock[0])
    for timestamp, amount in [(0, 0), (1, 100), (2, 200), (10, 400), (11, 500), (12, 600)]:
        clock[0] = timestamp
        progress = tracker.update(0, amount, 1000)
    assert progress["speed"] == 100
    assert progress["eta_seconds"] == 4
