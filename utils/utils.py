import asyncio
import math
import re
import os
import sys
import threading


def extract_substring(text, pattern):
    result = re.search(pattern, text)    
    if result:
        return result.group()
    return ""


def start_thread(callable, use_asyncio=True, args=None):
    if use_asyncio:
        def asyncio_wrapper():
            asyncio.run(callable())

        target_func = asyncio_wrapper
    else:
        target_func = callable

    if args:
        thread = threading.Thread(target=target_func, args=args)
    else:
        thread = threading.Thread(target=target_func)

    thread.daemon = True  # Daemon threads exit when the main process does
    thread.start()


def periodic(run_obj, sleep_attr="", run_attr=None):
    def scheduler(fcn):
        async def wrapper(*args, **kwargs):
            while True:
                asyncio.create_task(fcn(*args, **kwargs))
                period = int(run_obj) if isinstance(run_obj, int) else getattr(run_obj, sleep_attr)
                await asyncio.sleep(period)
                if run_obj and run_attr and not getattr(run_obj, run_attr):
                    print(f"Ending periodic task: {run_obj.__name__}.{run_attr} = False")
                    break
        return wrapper
    return scheduler


def open_file_location(filepath):
    if sys.platform=='win32':
        os.startfile(filepath)
    elif sys.platform=='darwin':
        subprocess.Popen(['open', filepath])
    else:
        try:
            subprocess.Popen(['xdg-open', filepath])
        except OSError:
            # er, think of something else to try
            # xdg-open *should* be supported by recent Gnome, KDE, Xfce
            raise Exception("Unsupported distribution for opening file location.")

def string_distance(s, t):
    # create two work vectors of integer distances
    v0 = [0] * (len(t) + 1)
    v1 = [0] * (len(t) + 1)

    # initialize v0 (the previous row of distances)
    # this row is A[0][i]: edit distance from an empty s to t;
    # that distance is the number of characters to append to  s to make t.
    for i in range(len(t) + 1):
        v0[i] = i

    for i in range(len(s)):
        # calculate v1 (current row distances) from the previous row v0

        # first element of v1 is A[i + 1][0]
        # edit distance is delete (i + 1) chars from s to match empty t
        v1[0] = i + 1

        for j in range(len(t)):
            # calculating costs for A[i + 1][j + 1]
            deletion_cost = v0[j + 1] + 1
            insertion_cost = v1[j] + 1
            substitution_cost = v0[j] if s[i] == t[j] else v0[j] + 1
            v1[j + 1] = min(deletion_cost, insertion_cost, substitution_cost)
        # copy v1 (current row) to v0 (previous row) for next iteration
        v0,v1 = v1,v0
    # after the last swap, the results of v1 are now in v0
    return v0[len(t)]

def longest_common_substring(str1, str2):
    m = [[0] * (1 + len(str2)) for _ in range(1 + len(str1))]
    longest, x_longest = 0, 0
    for x in range(1, 1 + len(str1)):
        for y in range(1, 1 + len(str2)):
            if str1[x - 1] == str2[y - 1]:
                m[x][y] = m[x - 1][y - 1] + 1
                if m[x][y] > longest:
                    longest = m[x][y]
                    x_longest = x
            else:
                m[x][y] = 0
    return str1[x_longest - longest: x_longest]


def is_similar_str(s0, s1):
    l_distance = string_distance(s0, s1)
    min_len = min(len(s0), len(s1))
    if min_len == len(s0):
        weighted_avg_len = (len(s0) + len(s1) / 2) / 2
    else:
        weighted_avg_len = (len(s0) / 2 + len(s1)) / 2
    threshold = int(weighted_avg_len / 2.1) - int(math.log(weighted_avg_len))
    threshold = min(threshold, int(min_len * 0.8))
    return l_distance < threshold

def remove_substring_by_indices(string, start_index, end_index):
    if end_index < start_index:
        raise Exception("End index was less than start for string: " + string)
    if end_index >= len(string) or start_index >= len(string):
        raise Exception("Start or end index were too high for string: " + string)
    if start_index == 0:
        print("Removed: " + string[:end_index+1])
        return string[end_index+1:]
    left_part = string[:start_index]
    right_part = string[end_index+1:]
    print("Removed: " + string[start_index:end_index+1])
    return left_part + right_part

def split(string, delimiter=","):
    # Split the string by the delimiter and clean any delimiter escapes present in the string
    parts = []
    i = 0
    while i < len(string):
        if string[i] == delimiter:
            if i == 0 or string[i-1] != "\\":
                parts.append(string[:i])
                string = string[i+1:]
                i = -1
            elif i != 0 and string[i-1] == "\\":
                string = string[:i-1] + delimiter + string[i+1:]
        i += 1
    print("Parts: " + str(parts))
    if len(parts) == 0 and len(string) != 0:
        parts.append(string)
    return parts
