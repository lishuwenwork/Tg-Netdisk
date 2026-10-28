import asyncio

import pytest

from tg_netdisk.services.reporting import ProgressReporter


async def test_network_progress_never_waits_for_database_and_final_state_is_drained():
    entered, release = asyncio.Event(), asyncio.Event()
    values = []

    async def slow_database(value):
        entered.set()
        await release.wait()
        values.append(value)

    reporter = ProgressReporter([1000, 1000], slow_database, interval=0)
    await reporter.progress(0, 10, 100)
    await asyncio.wait_for(entered.wait(), 1)
    await asyncio.wait_for(reporter.progress(0, 100, 100), 0.1)
    await asyncio.wait_for(reporter.progress(1, 200, 200), 0.1)
    release.set()
    await reporter.close()
    assert values[-1]["sent"] == values[-1]["total"] == 300
    assert reporter.worker.done()


async def test_burst_callbacks_are_coalesced():
    values = []

    async def emit(value):
        values.append(value)

    reporter = ProgressReporter([100], emit)
    for sent in range(1, 101):
        await reporter.progress(0, sent, 100)
    await reporter.close()
    assert len(values) == 1
    assert values[0]["sent"] == 100


async def test_reporter_failure_is_observed_before_publishing():
    async def failure(_):
        raise RuntimeError("database failed")

    reporter = ProgressReporter([100], failure)
    await reporter.progress(0, 100, 100)
    with pytest.raises(RuntimeError, match="database"):
        await reporter.close()
    assert reporter.worker.done()
