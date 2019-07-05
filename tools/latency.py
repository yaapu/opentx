#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (C) OpenTX
#
# Based on code named
#   th9x - http://code.google.com/p/th9x
#   er9x - http://code.google.com/p/er9x
#   gruvin9x - http://code.google.com/p/gruvin9x
#
# License GPLv2: http://www.gnu.org/licenses/gpl-2.0.html
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.


import argparse
import csv
import os


def build_transitions_array(f, column):
    f.seek(0)
    reader = csv.reader(f, delimiter=',')
    last = None
    transitions = []
    for i, row in enumerate(reader):
        if i == 0:
            continue
        value = row[column]
        if last is None or value != last:
            transitions.append((float(row[0]) * 1000, int(value)))
            last = value
    debounced = []
    i = 0
    while i < len(transitions):
        t, val = transitions[i]
        if i < len(transitions) - 1 and transitions[i+1][0] - t < 0.002:
            i += 2
            continue
        debounced.append((t, val))
        i += 1
    return debounced


class SBusFrame:
    def __init__(self):
        self.transitions = []

    def push(self, t, value):
        self.transitions.append((t, value))

    def start(self):
        return self.transitions[0][0]

    def end(self):
        return self.transitions[-1][0]

    def is_after(self, t):
        return self.start() >= t

    def value(self, time):
        value = 0
        for t, v in self.transitions:
            if t > time:
                return value
            value = v
        return value

    def byte(self, index):
        t = self.start() + 0.12 * index + 0.015
        value = 0
        for bit in range(8):
            value += (1 - self.value(t)) << bit
            t += 0.010
        return value

    def is_lost(self):
        return self.byte(23) & 0x04

    def __str__(self):
        return "%.03fms " % self.start() + " ".join(["%02X" % self.byte(i) for i in range(25)])

    @staticmethod
    def get_frames(transitions):
        result = []
        current_frame = None
        last = 0
        for t, value in transitions:
            if t - last > 2:
                if current_frame:
                    result.append(current_frame)
                current_frame = SBusFrame()
            if current_frame is not None:
                current_frame.push(t, value)
            last = t
        return result


class LatencyStatistics:
    def __init__(self, trigger_transitions, sbus_frames, highval, lowval):
        self.trigger_transitions = trigger_transitions
        self.sbus_frames = sbus_frames
        self.highval = highval
        self.lowval = lowval

    def iter(self):
        for t0, val in self.trigger_transitions[1:]:
            byte = self.highval if val == 1 else self.lowval
            for frame in self.sbus_frames:
                if frame.is_after(t0) and frame.byte(1) == byte:
                    delay = frame.end() - t0
                    yield (t0, val, frame, delay)
                    break

    @staticmethod
    def append_to_line(f, s, index, lines, columns):
        if columns == 0:
            f.write(s)
        elif index < len(lines):
            f.write(lines[index].strip() + ";" + s)
        else:
            f.write(";" * columns + s)
        f.write("\n")

    def export(self, path, title, append):
        lines = []
        columns = 0
        if append and os.path.exists(path):
            with open(path, 'r') as f:
                lines = f.readlines()
                columns = len(lines[0].split(";"))
        with open(path, 'w') as f:
            self.append_to_line(f, title, 0, lines, columns)
            index = 1
            for t0, val, frame, delay in self.iter():
                self.append_to_line(f, str(delay), index, lines, columns)
                index += 1

    def print(self):
        mini, maxi = None, None
        count = 0
        total = 0
        for t0, val, frame, delay in self.iter():
            count += 1
            total += delay
            if mini is None or delay < mini[0]:
                mini = (delay, t0, frame)
            if maxi is None or delay > maxi[0]:
                maxi = (delay, t0, frame)

        print("Delay between the switch toggle and the end of the SBUS frame:")
        print("  Count = %d transitions" % count)
        print("  Average = %.1fms" % (total / count))
        print("  Mini = %.1fms @ %fs" % (mini[0], mini[1] / 1000))
        print("  Maxi = %.1fms @ %fs" % (maxi[0], maxi[1] / 1000))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('file', help='File to parse', type=argparse.FileType('r'))
    parser.add_argument('--trigger', help='The column in the csv file where is your trigger', type=int, required=True)
    parser.add_argument('--pwm', help='The column in the csv file where is your PWM output', type=int)
    parser.add_argument('--sbus', help='The column in the csv file where is your SBUS output', type=int)
    parser.add_argument('--highval', help='The value of SBUS byte 2 when trigger=HIGH', type=int, default=0x13)
    parser.add_argument('--lowval', help='The value of SBUS byte 2 when trigger=LOW', type=int, default=0xAC)
    parser.add_argument('--export', help='CSV file to export latency values')
    parser.add_argument('--title', help='CSV column title', default="Unknown")
    parser.add_argument('--append', action='store_true')
    args = parser.parse_args()
    if not args.pwm and not args.sbus:
        print("Either a PWM or SBUS column in CSV must be specified")
        exit()

    trigger_transitions = build_transitions_array(args.file, args.trigger)

    sbus_transitions = build_transitions_array(args.file, args.sbus)
    sbus_frames = SBusFrame.get_frames(sbus_transitions)
    for frame in sbus_frames:
        if frame.is_lost():
            print("Frame lost bit @ %fs" % frame.start())

    statistics = LatencyStatistics(trigger_transitions, sbus_frames, args.highval, args.lowval)
    if args.export:
        statistics.export(args.export, args.title, args.append)
    statistics.print()


if __name__ == "__main__":
    main()
