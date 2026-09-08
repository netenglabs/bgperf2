'''The four recorded 10 x 1,050,000 MRT runs, replayed through the rules.

These are the series `bgperf2-dcs` was opened on: a 10-injector bgpdump2 run
against BIRD 3.3.2 on the campaign host, whose monitor count overshoots while a
minority of injectors have finished and then settles 1.2%-1.5% below that peak
as the rest complete. Three of the four were reported FAILED by a rule that had
only the monitor to go on, and every one of them settled on the same
1,056,779 -- the failure is a property of the workload, not of a bad run.

Each pair is (monitor accepted, the target's own best-path count) from one
monitor poll of `<prefix>.events.json`'s `target_table` section, in order.
Evidence: results/2026/phase6-calibration/mrt-witness-1 .. -4 on the campaign
host (`results/` is gitignored, so the numbers are copied here -- a rule
written against a series nobody can re-read is not auditable).

Two things about the replay are idealised, and neither touches what is being
pinned: the neighbour bookkeeping is fed as ten steady neighbours with the
checkpoint set when the monitor first reaches the check-point, and the samples
are dated one second apart. What is real is the two counts and their order.
'''
from convergence import ConvergenceTracker

# 99% of the configured 1,050,000, which is what gen_conf() gives the monitor.
CHECK_POINT = 1039500

# (monitor_accepted, best_paths) per monitor poll, per run.
RECORDED = {
    1: [
        (0, 0), (0, 0), (32203, 131829), (195876, 212309), (221220, 228567),
        (316258, 340726), (425848, 425894), (521097, 524345),
        (593018, 594914), (691057, 733604), (781088, 811409),
        (883555, 890195), (995654, 1001155), (948739, 1057568),
        (778803, 1058190), (774094, 1058246), (851136, 1059343),
        (912148, 1059473), (914964, 1060958), (963230, 1070817),
        (1029752, 1072274), (1051445, 1077075), (1050572, 1077861),
        (1051131, 1078468), (1051395, 1079325), (1053113, 1079398),
        (1049968, 1079631), (1051585, 1079667), (1054018, 1079765),
        (1055035, 1080249), (1056779, 1080985), (1056779, 1080985),
        (1056779, 1080985), (1056779, 1080985), (1056779, 1080985),
        (1056779, 1080985),
    ],
    2: [
        (0, 0), (0, 0), (27451, 131829), (209919, 131829), (220239, 238622),
        (300674, 347503), (412741, 464568), (504492, 524634),
        (577832, 599244), (658850, 681550), (698885, 711828),
        (723281, 754226), (751345, 777780), (848975, 874434),
        (984681, 982370), (1052981, 1067661), (1060793, 1068317),
        (1062649, 1070498), (1068469, 1077122), (1069377, 1077449),
        (1065405, 1080044), (1061391, 1078734), (1062594, 1079465),
        (1064885, 1079685), (1065007, 1080131), (1062099, 1079821),
        (1060086, 1081194), (1060471, 1080395), (1056779, 1080985),
        (1056779, 1080985), (1056779, 1080985), (1056779, 1080985),
        (1056779, 1080985), (1056779, 1080985), (1056779, 1080985),
        (1056779, 1080985), (1056779, 1080985), (1056779, 1080985),
    ],
    3: [
        (0, 0), (0, 0), (30907, 98450), (185865, None), (227301, 227308),
        (332112, 339363), (410798, 430299), (513794, 509618),
        (595620, 596355), (678252, 728127), (782898, 832801),
        (897541, 912218), (995072, 1049035), (1056934, 1066423),
        (1059033, 1067906), (1061720, 1068551), (1059953, 1069091),
        (1056987, 1070038), (1058876, 1070066), (1056714, 1070083),
        (1055764, 1070181), (1056127, 1070227), (1065372, 1070251),
        (1065418, 1070494), (1065646, 1070516), (1067610, 1073656),
        (1067616, 1072722), (1068280, 1072976), (1071837, 1077179),
        (1072157, 1077609), (1072575, 1078329), (1071712, 1079507),
        (1070462, 1080408), (1067796, 1080085), (1065797, 1080520),
        (1065934, 1080648), (1063344, 1080706), (1058922, 1080961),
        (1056779, 1080985), (1056779, 1080985), (1056779, 1080985),
        (1056779, 1080985), (1056779, 1080985), (1056779, 1080985),
        (1056779, 1080985), (1056779, 1080985), (1056779, 1080985),
    ],
    4: [
        (0, 0), (0, 0), (1538, 32776), (192402, None), (223111, 226419),
        (292668, 306229), (411486, 416776), (492845, 519059),
        (579718, 581012), (659461, 661956), (742826, 792875),
        (863157, 872672), (976798, 980540), (1044024, 1055596),
        (1043584, 1056087), (1048770, 1056909), (1047711, 1057115),
        (1045689, 1057248), (1044651, 1058888), (1050085, 1068701),
        (1064330, 1071024), (1065408, 1076534), (1071193, 1076683),
        (1070626, 1077472), (1071007, 1077878), (1070686, 1078551),
        (1068007, 1079118), (1064862, 1079568), (1065438, 1080124),
        (1062313, 1080259), (1057395, 1080534), (1056779, 1080985),
        (1056779, 1080985), (1056779, 1080985), (1056779, 1080985),
        (1056779, 1080985), (1056779, 1080985), (1056779, 1080985),
        (1056779, 1080985), (1056779, 1080985),
    ],
}

# What each run was reported as before the target was asked anything.
RECORDED_VERDICT_FROM_THE_MONITOR_ALONE = {
    1: ConvergenceTracker.CONVERGED,
    2: ConvergenceTracker.FAILED,
    3: ConvergenceTracker.FAILED,
    4: ConvergenceTracker.FAILED,
}


def replay(series, with_witness=True, loss_after_peak=1.0):
    """Feed one recorded run to a tracker and return (status, tracker).

    `loss_after_peak` shrinks the target's own count from the monitor's peak
    onward, which is what these runs would have recorded had the decline been
    routes going away rather than best paths changing. Applied from the peak
    rather than throughout, because a series scaled end to end has the same
    decline from its own high-water mark and is the same measurement in
    different units.
    """
    tracker = ConvergenceTracker()
    status = ConvergenceTracker.CONTINUE
    peak_at = max(range(len(series)), key=lambda i: series[i][0])
    for i, (monitor, best_paths) in enumerate(series):
        checked = monitor >= CHECK_POINT
        if checked:
            tracker.note_neighbors_checkpoint()
        witness = None
        if with_witness and best_paths is not None:
            scale = loss_after_peak if i >= peak_at else 1.0
            witness = {'best_paths': int(best_paths * scale)}
        status = tracker.update(i, monitor, 10, 10, checked,
                                table_witness=witness,
                                witness_monotonic_s=float(i))
        if status != ConvergenceTracker.CONTINUE:
            break
    return status, tracker


def test_the_monitor_alone_fails_three_of_the_four_recorded_runs():
    """The bug, pinned: one command, two verdicts, and the majority wrong."""
    for run, series in RECORDED.items():
        status, _ = replay(series, with_witness=False)
        assert status == RECORDED_VERDICT_FROM_THE_MONITOR_ALONE[run], run


def test_all_four_converge_once_the_target_is_asked():
    """The target's table reaches 1,080,985 in every one of these runs and
    holds it, so nothing was lost and every run converged."""
    for run, series in RECORDED.items():
        status, tracker = replay(series)
        assert status == ConvergenceTracker.CONVERGED, run
        # 1,080,985 to the prefix in all four, except run 2, whose table really
        # did wobble by 209 prefixes -- which is why the rule is a threshold on
        # the target's own decline and not a test that it is flat.
        assert tracker.peak_best_paths in (1080985, 1081194), run


def test_the_three_that_failed_say_the_witness_decided_them():
    """A verdict that rests on the witness says so in the artifact; the run
    that never overshot is decided without it and publishes nothing."""
    for run in (2, 3, 4):
        _, tracker = replay(RECORDED[run])
        rule = tracker.witness_rule()
        assert rule['converged_below_monitor_peak'] is True, run
        # The recorded monitor declines: 1.18%, 1.47% and 1.35%.
        assert 0.011 <= rule['max_excused_monitor_decline'] <= 0.015, run
        # ...against a target table that moved by 209 prefixes at the very
        # most, which is the whole basis of the rule.
        assert rule['max_witness_decline_while_excusing'] <= 0.0002, run
    assert replay(RECORDED[1])[1].witness_rule()['excused_samples'] > 0


def test_a_loss_the_target_shared_still_fails():
    """The same series with the target's own count falling in step -- what
    real route loss would have recorded -- is not excused."""
    for run in (2, 3, 4):
        status, _ = replay(RECORDED[run], loss_after_peak=0.95)
        assert status == ConvergenceTracker.FAILED, run
