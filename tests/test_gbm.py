import numpy as np

from epiprot.gbm.context import causal_mean
from epiprot.gbm.events import PatientSeries, alarms, evaluate
from epiprot.gbm.labels import relabel


def _toy_labels():
    # 300 interictal, 50 pre-ictal, 13 gap+ictal, 200 after
    return np.r_[np.zeros(300), np.ones(50), -np.ones(13), np.zeros(200)].astype(np.float32)


def test_relabel_excludes_postictal_and_prebuffer():
    yc, events = relabel(_toy_labels(), postictal_min=60, pre_buffer_min=30)
    assert len(events) == 1 and (events[0].pos_start, events[0].pos_end) == (300, 350)
    assert (yc[240:300] == -1).all()          # 30 min before pre-ictal excluded
    assert (yc[:240] == 0).all()
    assert (yc[363:363 + 120] == -1).all()    # 60 min post-ictal excluded
    assert (yc[363 + 120:] == 0).all()


def test_relabel_drops_cluster_seizure_preictal():
    y = np.r_[np.zeros(300), np.ones(50), -np.ones(13), np.ones(50), -np.ones(13),
              np.zeros(300)].astype(np.float32)
    yc, events = relabel(y)
    assert len(events) == 1                  # second seizure is inside post-ictal of first
    assert (yc[363:413] == -1).all()


def test_causal_mean_uses_only_past():
    x = np.arange(6, dtype=np.float32)[:, None]
    np.testing.assert_allclose(causal_mean(x, 3)[:, 0], [0, 0.5, 1, 2, 3, 4])


def test_alarm_refractory_and_event_scoring():
    assert list(alarms(np.array([0, 1, 1, 1, 0, 1]), 0.5, refractory=3)) == [1, 5]
    yc, events = relabel(_toy_labels())
    prob = np.zeros(len(yc))
    prob[310] = 1.0   # inside pre-ictal -> hit
    prob[100] = 1.0   # clean interictal -> false alarm
    r = evaluate([PatientSeries("s", prob, yc, events)], thr=0.5, k=1)
    assert r["predicted"] == 1 and r["false_alarms"] == 1
