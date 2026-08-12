# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
# Scoring the Water Pump  (medium)
#
# A village water tank has a sensor. It writes down the water level in centimetres once
# a minute, all day. The village is testing a new pump. They score the pump by how
# steady the level stayed. A run of minutes counts as steady if, inside that run, the
# highest level is at most a set number of centimetres above the lowest level. They
# count every steady run: one minute on its own, two minutes in a row, and so on. A
# short steady run sitting inside a longer steady run still counts. The score is the
# total number of steady runs.
#
# Return the score: the number of runs of one or more readings in a row whose highest
# reading minus lowest reading is at most allowed_gap. A run is fixed by its first
# minute and its last minute, so two runs are different whenever their first minutes
# differ or their last minutes differ, even if the readings inside them look the same. A
# run of a single reading is always steady, since its highest and lowest reading are the
# same. If the list of readings is empty, return 0.
#
# Constraints:
#   - There are between 0 and 200000 readings, given in time order, one per minute.
#   - Each reading is a whole number of centimetres from 0 to 1000.
#   - allowed_gap is a whole number of centimetres from 0 to 1000.
#   - The score can be very large; return the exact whole number.


class Solution:

    def count_steady_stretches(self, readings: list[int], allowed_gap: int) -> int:
        pass
