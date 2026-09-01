from pathlib import Path


def test_launch_watch_has_bounded_off_minute_schedule_and_merge_trigger():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "watch-launch-venues.yml"
    ).read_text(encoding="utf-8")

    trigger = workflow[workflow.index("on:") : workflow.index("permissions:")]
    assert 'cron: "7-59/10 * * * *"' in trigger
    assert 'cron: "*/15 * * * *"' not in trigger
    assert (
        'push:\n'
        '    branches:\n'
        '      - main\n'
        '    paths:\n'
        '      - ".github/workflows/watch-launch-venues.yml"'
    ) in trigger

    assert "group: narrative-radar-launch-watch" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "cancel-in-progress: true" not in workflow
    timeout_line = next(
        line for line in workflow.splitlines() if "timeout-minutes:" in line
    )
    timeout_minutes = int(timeout_line.split(":", 1)[1].strip())
    assert 0 < timeout_minutes < 10


def test_scheduled_feed_persistence_is_separate_from_alerting():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "discover-narratives.yml"
    ).read_text(encoding="utf-8")

    persist_start = workflow.index("- name: Persist the current scheduled narrative feed")
    notify_start = workflow.index("- name: Notify on a material narrative update")
    upload_start = workflow.index("- name: Upload discovery report")
    persist_step = workflow[persist_start:notify_start]
    notify_step = workflow[notify_start:upload_start]

    assert "group: narrative-radar-discovery-feed" in workflow
    assert "env.TOPIC == 'crypto narratives'" in persist_step
    assert "env.CHAIN == 'unknown'" in persist_step
    assert "issue.user?.login === 'github-actions[bot]'" in persist_step
    assert "body," in persist_step
    assert "core.setOutput('notify'" in persist_step
    assert "issues.createComment" not in persist_step

    assert "steps.persist_feed.outputs.notify == 'true'" in notify_step
    assert "issues.createComment" in notify_step
    assert "narrative-radar-discovery-alert" in notify_step
    assert "narrative-radar-discovery-report" not in notify_step
