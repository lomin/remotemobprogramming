# Copyright (C) 2026 Steven Collins
# SPDX-License-Identifier: AGPL-3.0-only
# Scoring the Water Pump  (medium)
#
# A sensor in a village water tank records the water level, in centimetres, once a
# minute. The village is testing a new pump, and wants to know how steady the level
# stayed while it ran.
#
# A stretch is any block of consecutive readings: minutes 3 to 7, say, or a single
# minute on its own. A stretch is steady if the level never wandered far inside it —
# that is, if (highest reading in the stretch) - (lowest reading in the stretch) is at
# most allowed_gap.
#
# Count every steady stretch. Stretches may overlap, and a steady stretch sitting inside
# a longer steady stretch still counts on its own. A stretch is identified by where it
# starts and where it ends, so two stretches are different whenever their start minutes
# differ or their end minutes differ, even if they hold the same readings. A stretch of a
# single reading is always steady, because its highest and lowest reading are the same
# number, so the difference is 0.
#
# Example: readings = [30, 50, 40, 80], allowed_gap = 20 -> 7
#   The 4 single readings are all steady.
#   [30, 50] -> 50 - 30 = 20, steady.   [50, 40] -> 10, steady.
#   [40, 80] -> 40, too big.            [30, 50, 40] -> 20, steady.
#   [50, 40, 80] -> 40, and [30, 50, 40, 80] -> 50, both too big.
#   4 + 3 = 7.
#
# If the list of readings is empty, return 0.
#
# Constraints:
#   - There are between 0 and 200000 readings, given in time order, one per minute.
#   - Each reading is a whole number of centimetres from 0 to 1000.
#   - allowed_gap is a whole number of centimetres from 0 to 1000.
#   - The answer can be very large; return the exact whole number.


class Solution:

    def count_steady_stretches(self, readings: list[int], allowed_gap: int) -> int:
        candidates = []
        for i in range(len(readings)):
            for j in range(i, len(readings)):
                stretch = readings[i:j+1]
                if abs(max(stretch) - min(stretch)) <= allowed_gap:
                    candidates.append(stretch)
        return len(candidates)
