# Copyright 2020 The T5 Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Utility functions for running offline evaluation."""

import collections
import os

from absl import logging
import numpy as np
import pandas as pd
import tensorflow.compat.v1 as tf


class Metric(object):

  def __init__(self, name, group=None):
    self.name = name
    self.group = group or name

# This OrderedDict maps TensorBoard tags to nice-looking metric names.
# The order of the keys in the dict determine the order they get logged.
METRIC_NAMES = collections.OrderedDict([
    ("glue_average", Metric("Average GLUE Score")),
    ("glue_cola_v002/matthews_corrcoef", Metric("CoLA")),
    ("glue_sst2_v002/accuracy", Metric("SST-2")),
    ("glue_mrpc_v002/f1", Metric("MRPC (F1)", "MRPC")),
    ("glue_mrpc_v002/accuracy", Metric("MRPC (accuracy)", "MRPC")),
    ("glue_stsb_v002/pearson_corrcoef", Metric("STSB (Pearson)", "STSB")),
    ("glue_stsb_v002/spearman_corrcoef", Metric("STSB (Spearman)", "STSB")),
    ("glue_qqp_v002/f1", Metric("QQP (F1)", "QQP")),
    ("glue_qqp_v002/accuracy", Metric("QQP (accuracy)", "QQP")),
    ("glue_mnli_matched_v002/accuracy", Metric("MNLIm", "MNLI")),
    ("glue_mnli_mismatched_v002/accuracy", Metric("MNLImm", "MNLI")),
    ("glue_qnli_v002/accuracy", Metric("QNLI")),
    ("glue_rte_v002/accuracy", Metric("GLUE RTE")),
    ("cnn_dailymail_v002/rouge1", Metric("CNN/DM (ROUGE-1)", "CNN/DM")),
    ("cnn_dailymail_v002/rouge2", Metric("CNN/DM (ROUGE-2)", "CNN/DM")),
    ("cnn_dailymail_v002/rougeL", Metric("CNN/DM (ROUGE-L)", "CNN/DM")),
    ("cnn_dailymail_v002/rougeLsum", Metric("CNN/DM (ROUGE-L)", "CNN/DM")),
    ("squad_v010_allanswers/em", Metric("SQuAD (EM)", "SQuAD")),
    ("squad_v010_allanswers/f1", Metric("SQuAD (F1)", "SQuAD")),
    ("squad_v010_allanswers_span/em", Metric("SQuAD (EM)", "SQuAD")),
    ("squad_v010_allanswers_span/f1", Metric("SQuAD (F1)", "SQuAD")),
    ("squad_v010/em", Metric("SQuAD (EM)", "SQuAD")),
    ("squad_v010/f1", Metric("SQuAD (F1)", "SQuAD")),
    ("super_glue_average", Metric("Average SuperGLUE Score")),
    ("super_glue_boolq_v102/accuracy", Metric("BoolQ (accuracy)")),
    ("super_glue_cb_v102/mean_3class_f1", Metric("CB (F1)", "CB")),
    ("super_glue_cb_v102/accuracy", Metric("CB (accuracy)", "CB")),
    ("super_glue_copa_v102/accuracy", Metric("CoPA")),
    ("super_glue_multirc_v102/f1", Metric("MultiRC (F1)", "MultiRC")),
    ("super_glue_multirc_v102/exact_match", Metric("MultiRC (EM)", "MultiRC")),
    ("super_glue_record_v102/f1", Metric("ReCoRD (F1)", "ReCoRD")),
    ("super_glue_record_v102/em", Metric("ReCoRD (EM)", "ReCoRD")),
    ("super_glue_rte_v102/accuracy", Metric("SuperGLUE RTE")),
    ("super_glue_wic_v102/accuracy", Metric("WiC")),
    ("super_glue_wsc_v102_simple_eval/accuracy", Metric("WSC")),
    ("dpr_v001_simple/accuracy", Metric("DPR")),
    ("wmt_t2t_ende_v003/bleu", Metric("WMT T2T En-De")),
    ("wmt14_ende_v003/bleu", Metric("WMT14 En-De")),
    ("wmt15_enfr_v003/bleu", Metric("WMT15 En-Fr")),
    ("wmt16_enro_v003/bleu", Metric("WMT16 En-Ro")),
])

Event = collections.namedtuple("event", ["step", "value"])


def parse_events_files(tb_summary_dir):
  """Parse all TensorBoard events files in tb_summary_dir.

  Args:
    tb_summary_dir: str, path to look for events files in.

  Returns:
    A dict, where each key is a TensorBoard tag and each value is a list of
    Event tuples with step and value attributes.
  """
  events = collections.defaultdict(list)
  for events_file in tf.gfile.Glob(os.path.join(tb_summary_dir, "events.*")):
    try:
      for e in tf.train.summary_iterator(events_file):
        for v in e.summary.value:
          events[v.tag].append(Event(e.step, v.simple_value))
    except tf.errors.DataLossError:
      logging.info("Skipping %s due to truncated record.", events_file)
  return events


def get_eval_metric_values(events):
  """Filter TensorBoard events to only include those for eval metrics.

  Args:
    events: dict of list of (step, value) tuples where keys are tags.

  Returns:
    Dict where key is task_name/metric_name and value is (step, value) tuple.
  """
  eval_values = {}
  for tag, event_values in events.items():
    if tag.startswith("eval"):
      _, task_name, metric_name = tag.split("/")
      eval_values["{}/{}".format(task_name, metric_name)] = event_values
  return eval_values


def sort_columns(df, metric_names=None):
  metric_names = metric_names or METRIC_NAMES
  column_order = list(collections.OrderedDict.fromkeys(
      [m.name for m in metric_names.values() if m.name in df.columns]
  ))
  return df.reindex(columns=column_order)


def compute_avg_glue(df, metric_names=None):
  """Compute average GLUE and SuperGLUE scores from a DataFrame.

  Will only compute a given average score if all of the metrics for that
  benchmark appear as columns in the DataFrame.

  Args:
    df: pandas.DataFrame, columns should be metric names.
    metric_names: dict mapping tensorboard tag to metric name.
  Returns:
    A pandas.DataFrame which has GLUE and SuperGLUE averages calculated.
  """
  # Use METRIC_NAMES defined at the top as default
  metric_names = metric_names or METRIC_NAMES
  all_glue_tags = {
      k for k in metric_names.keys() if "glue" in k and "average" not in k
  }
  superglue_tags = {k for k in all_glue_tags if "super" in k}
  glue_tags = all_glue_tags - superglue_tags
  average_keys = ["Average GLUE Score", "Average SuperGLUE Score"]
  for average_key, tags in zip(average_keys, [glue_tags, superglue_tags]):
    # Only compute average if all metric names appear as columns in the DF
    if {metric_names[t].name for t in tags}.issubset(set(df.columns)):
      # Compute average over each metric group
      group_to_metrics = collections.defaultdict(set)
      for tag in tags:
        metric = metric_names[tag]
        group_to_metrics[metric.group].add(metric.name)
      accum = None
      for metrics in group_to_metrics.values():
        group_avg = np.mean([df[k] for k in metrics], axis=0)
        accum = group_avg if accum is None else accum + group_avg
      # Compute average across all groups
      average = accum/len(group_to_metrics)
      df[average_key] = average
  return df


def scores_to_df(scores, metric_names=None):
  """Convert `scores` into a pandas DataFrame."""
  # Use METRIC_NAMES defined at the top as default
  metric_names = metric_names or METRIC_NAMES
  for tag in scores.keys():
    if tag not in metric_names:
      raise ValueError(
          "TensorBoard tag {} not found in metric_names. Known tags: {}".format(
              tag, metric_names.keys()
          )
      )

  # Sort the tags in scores according to metric_names order
  sorted_tags = sorted(
      scores.keys(), key=lambda x: list(metric_names.keys()).index(x)
  )
  columns = [metric_names[t].name for t in sorted_tags]

  # Convert scores to dict with the format
  # {step_number: {tag1: value, tag2: value, ...}}
  step_scores = collections.defaultdict(
      lambda: collections.OrderedDict([(t, np.nan) for t in sorted_tags])
  )
  for tag in sorted_tags:
    for step, value in scores[tag]:
      step_scores[step][tag] = value
  sorted_items = sorted(list(step_scores.items()))
  data = [list(r.values()) for _, r in sorted_items]
  index = [s for s, _ in sorted_items]
  df = pd.DataFrame(data, index, columns)
  df.index.name = "step"
  return df


def metric_group_max(df, metric_names=None):
  """Find the step which achieves the highest mean value for a group of metrics."""
  # Use METRIC_NAMES defined at the top as default
  metric_names = metric_names or METRIC_NAMES
  group_to_metrics = collections.defaultdict(set)
  for metric in metric_names.values():
    group_to_metrics[metric.group].add(metric.name)
  group_df = pd.DataFrame()
  for group, metrics in group_to_metrics.items():
    if not all(m in df for m in metrics):
      continue
    group_df[group] = df[metrics].mean(axis=1)
  # Need to replace nan with large negative value for idxmax
  group_max_step = group_df.fillna(-1e9).idxmax(axis=0)
  metric_max = pd.Series()
  metric_max_step = pd.Series()
  for group_name, max_step in group_max_step.iteritems():
    for metric in group_to_metrics[group_name]:
      metric_max[metric] = df[metric][max_step]
      metric_max_step[metric] = max_step
  metric_max = metric_max.reindex(df.columns)
  metric_max_step = metric_max_step.reindex(df.columns)
  return metric_max, metric_max_step


def log_csv(df, metric_names=None, output_file=None):
  """Log scores to be copy/pasted into a spreadsheet."""
  logging.info(",".join(df.columns))
  metric_max, metric_max_step = metric_group_max(df, metric_names)
  max_row = "max," + ",".join("{:.3f}".format(m) for m in metric_max)
  logging.info(max_row)
  idx_row = "step," + ",".join("{:d}".format(i) for i in metric_max_step)
  logging.info(idx_row)

  if output_file is not None:
    with tf.io.gfile.GFile(output_file, "w") as f:
      csv_string = df.to_csv(float_format="%.3f")
      f.write(csv_string + max_row + "\n" + idx_row)
