import asyncio
import glob
import logging
import math
import random
import re
import os
import sys
import threading

from utils.config import config

has_imported_windll = False
try:
    from ctypes import WinDLL
    has_imported_windll = True
except ImportError as e:
    print("Failed to import WinDLL, skipping sleep prevention.")


from utils.logging_setup import get_logger

RESET = "\033[m"
GRAY = "\033[90m"
WHITE = "\033[37m"
DARK_RED = "\033[91m"
DARK_GREEN = "\033[92m"
CYAN = "\033[34m"

# create logger
logger = get_logger("sd_runner")


class Utils:
    # Regular expression to match emoji characters
    EMOJI_PATTERN = re.compile("["
        u"\U0001F600-\U0001F64F"  # emoticons
        # u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        # u"\U0001F680-\U0001F6FF"  # transport & map symbols
        # u"\U0001F700-\U0001F77F"  # alchemical symbols
        # u"\U0001F780-\U0001F7FF"  # Geometric Shapes
        # u"\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
        # u"\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
        # u"\U0001FA00-\U0001FA6F"  # Chess Symbols
        # u"\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
        u"\U00002702-\U000027B0"  # Dingbats
        # u"\U000024C2-\U0001F251"  # Enclosed characters
        "]+", flags=re.UNICODE)

    # List of valid non-emoji characters that are commonly used in filenames
    VALID_FILENAME_CHARS = {
        u"\uFF1A",  # Chinese colon (ï¼)
        u"\uFF0C",  # Chinese comma (ï¼)
        u"\u3001",  # Japanese comma (ã)
        u"\u3002",  # Japanese period (ã)
        u"\uFF01",  # Full-width exclamation mark (ï¼)
        u"\uFF1F",  # Full-width question mark (ï¼)
        u"\uFF08",  # Full-width left parenthesis (ï¼)
        u"\uFF09",  # Full-width right parenthesis (ï¼)
        u"\u3014",  # Left tortoise shell bracket (ã)
        u"\u3015",  # Right tortoise shell bracket (ã)
        u"\u3010",  # Left black lenticular bracket (ã)
        u"\u3011",  # Right black lenticular bracket (ã)
        u"\u300A",  # Left double angle bracket (ã)
        u"\u300B",  # Right double angle bracket (ã)
        u"\u3008",  # Left angle bracket (ã)
        u"\u3009",  # Right angle bracket (ã)
        u"\u300C",  # Left corner bracket (ã)
        u"\u300D",  # Right corner bracket (ã)
        u"\u300E",  # Left white corner bracket (ã)
        u"\u300F",  # Right white corner bracket (ã)
        u"\u3016",  # Left white lenticular bracket (ã)
        u"\u3017",  # Right white lenticular bracket (ã)
        u"\u3018",  # Left white tortoise shell bracket (ã)
        u"\u3019",  # Right white tortoise shell bracket (ã)
        u"\u301A",  # Left white square bracket (ã)
        u"\u301B",  # Right white square bracket (ã)
    }

    sleep_prevented = False

    @staticmethod
    def extract_substring(text, pattern):
        result = re.search(pattern, text)    
        if result:
            return result.group()
        return ""

    @staticmethod
    def start_thread(callable, use_asyncio=True, args=None):
        if use_asyncio:
            def asyncio_wrapper():
                result = callable()
                if result is not None:
                    if asyncio.iscoroutine(result):
                        asyncio.run(result)
                    else:
                        logger.error(f"Asyncio wrapper called with non-coroutine type: {type(result)} ({result})")

            target_func = asyncio_wrapper
        else:
            target_func = callable

        if args:
            thread = threading.Thread(target=target_func, args=args)
        else:
            thread = threading.Thread(target=target_func)

        thread.daemon = True  # Daemon threads exit when the main process does
        thread.start()

    @staticmethod
    def periodic(run_obj, sleep_attr="", run_attr=None):
        def scheduler(fcn):
            async def wrapper(*args, **kwargs):
                while True:
                    asyncio.create_task(fcn(*args, **kwargs))
                    period = int(run_obj) if isinstance(run_obj, int) else getattr(run_obj, sleep_attr)
                    await asyncio.sleep(period)
                    if run_obj and run_attr and not getattr(run_obj, run_attr):
                        logger.info(f"Ending periodic task: {run_obj.__name__}.{run_attr} = False")
                        break
            return wrapper
        return scheduler

    @staticmethod
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

    @staticmethod
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

    @staticmethod
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

    @staticmethod
    def is_similar_str(s0, s1):
        l_distance = Utils.string_distance(s0, s1)
        min_len = min(len(s0), len(s1))
        if min_len == len(s0):
            weighted_avg_len = (len(s0) + len(s1) / 2) / 2
        else:
            weighted_avg_len = (len(s0) / 2 + len(s1)) / 2
        threshold = int(weighted_avg_len / 2.1) - int(math.log(weighted_avg_len))
        threshold = min(threshold, int(min_len * 0.8))
        return l_distance < threshold

    @staticmethod
    def remove_substring_by_indices(string, start_index, end_index):
        if end_index < start_index:
            raise Exception("End index was less than start for string: " + string)
        if end_index >= len(string) or start_index >= len(string):
            raise Exception("Start or end index were too high for string: " + string)
        if start_index == 0:
            logger.debug("Removed: " + string[:end_index+1])
            return string[end_index+1:]
        left_part = string[:start_index]
        right_part = string[end_index+1:]
        logger.debug("Removed: " + string[start_index:end_index+1])
        return left_part + right_part

    @staticmethod
    def get_centrally_truncated_string(s, maxlen):
        # get centrally truncated string
        if len(s) <= maxlen:
            return s
        max_left_index = int((maxlen)/2-2)
        min_right_index = int(-(maxlen)/2-1)
        return s[:max_left_index] + "..." + s[min_right_index:]

    @staticmethod
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
            elif i == len(string) - 1:
                parts.append(string[:i+1])
            i += 1
        if len(parts) == 0 and len(string) != 0:
            parts.append(string)
        return parts

    @staticmethod
    def get_default_user_language():
        _locale = os.environ['LANG'] if "LANG" in os.environ else None
        if not _locale or _locale == '':
            if sys.platform == 'win32':
                import ctypes
                import locale
                windll = ctypes.windll.kernel32
                windll.GetUserDefaultUILanguage()
                _locale = locale.windows_locale[windll.GetUserDefaultUILanguage()]
                if _locale is not None and "_" in _locale:
                    _locale = _locale[:_locale.index("_")]
            # TODO support finding default languages on other platforms
            else:
                _locale = 'en'
        elif _locale is not None and "_" in _locale:
            _locale = _locale[:_locale.index("_")]
        return _locale

    @staticmethod
    def play_sound(sound="success"):
        if sys.platform != 'win32':
            return
        sound = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib", "sounds", sound + ".wav")
        import winsound
        winsound.PlaySound(sound, winsound.SND_ASYNC)

    @staticmethod
    def prevent_sleep(prevent_sleep: bool = False) -> None:
        if not has_imported_windll:
            return
        if prevent_sleep == Utils.sleep_prevented:
            return

        """Set system sleep behavior to keep the system awake and screen on"""
        # thread execution flags for enabling/disabling system sleep
        ES_SYSTEM_REQUIRED = 0x0001  # keep system awake
        ES_DISPLAY_REQUIRED = 0x0002  # keep display awake
        ES_CONTINUOUS = 0x8000_0000  # see MSDN SetThreadExecutionState docs
        kernel32 = WinDLL('kernel32', use_last_error=True)
        if prevent_sleep:  # prevent system sleep
            kernel32.SetThreadExecutionState(  # set to literal: 0x8000_0003
                (ES_CONTINUOUS | ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED)
            )
        else:  # allow system sleep
            kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        Utils.sleep_prevented = prevent_sleep

    # Comprehensive list of image file extensions
    IMAGE_EXTENSIONS = [
        ".jpg", ".jpeg", ".jpe", ".jif", ".jfif", ".jfi",  # JPEG variants
        ".png",  # PNG
        ".gif",  # GIF
        ".bmp", ".dib",  # BMP variants
        ".tiff", ".tif",  # TIFF variants
        ".webp",  # WebP
        ".svg", ".svgz",  # SVG variants
        ".ico", ".cur",  # Icon variants
        ".psd",  # Photoshop
        ".raw", ".arw", ".cr2", ".nrw", ".k25",  # RAW variants
        ".heic", ".heif",  # HEIF variants
        ".avif",  # AVIF
        ".jp2", ".j2k", ".jpf", ".jpx", ".jpm", ".mj2",  # JPEG 2000 variants
    ]

    @staticmethod
    def get_files_from_dir(dirpath, recursive=False, random_sort=False, allowed_extensions=None):
        if not os.path.isdir(dirpath):
            raise Exception(f"Not a directory: {dirpath}")
        glob_pattern = "**/*" if recursive else "*"
        files = glob.glob(os.path.join(dirpath, glob_pattern), recursive=recursive)

        # Filter by file extensions if provided
        if allowed_extensions:
            # Convert extensions to lowercase for case-insensitive comparison
            allowed_ext_lower = [ext.lower() for ext in allowed_extensions]
            filtered_files = []
            for file in files:
                # Get file extension (including the dot) and convert to lowercase
                file_ext = os.path.splitext(file)[1].lower()
                if file_ext in allowed_ext_lower:
                    filtered_files.append(file)
            files = filtered_files

        if random_sort:
            random.shuffle(files)
        else:
            files.sort()
        return files

    @staticmethod
    def get_random_file_from_dir(dirpath, recursive=False, allowed_extensions=None):
        files = Utils.get_files_from_dir(dirpath, recursive, random_sort=True, allowed_extensions=allowed_extensions)
        
        if not files:
            return None
        
        # Since files are already shuffled and filtered, just return the first one
        return files[0]

    @staticmethod
    def format_red(s):
        return f"{DARK_RED}{s}{RESET}"

    @staticmethod
    def format_green(s):
        return f"{DARK_GREEN}{s}{RESET}"

    @staticmethod
    def format_white(s):
        return f"{WHITE}{s}{RESET}"

    @staticmethod
    def format_cyan(s):
        return f"{CYAN}{s}{RESET}"

    @staticmethod
    def print_list_str(ls, newlines=True):
        out = f"["
        if newlines:
            out += "\n"
            for item in ls:
                out += f"\t{item}\n"
            out += "]"
        else:
            for i in range(len(ls)):
                item = ls[i]
                if i == len(ls) - 1:
                    out += f"{item}"
                else:
                    out += f"{item}, "
            out += "]"
        return out

    @staticmethod
    def preprocess_data_for_encryption(data: str) -> bytes:
        """
        Enhanced preprocessing with multiple obfuscation layers.
        """
        import zlib
        import base64
        
        data_bytes = data.encode('utf-8')
        fake_header = "MY_HEADER_v1.0_".encode('utf-8')
        fake_footer = "_END_DATA".encode('utf-8')
        wrapped_data = fake_header + data_bytes + fake_footer
        
        compressed_data = zlib.compress(wrapped_data, level=zlib.Z_BEST_COMPRESSION)
        
        xor_key = "L{ofT/r8tOJp".encode('utf-8')
        xored_data = bytes(a ^ b for a, b in zip(compressed_data, xor_key * (len(compressed_data) // len(xor_key) + 1)))
        
        base64_data = base64.b64encode(xored_data)
        
        reversed_data = base64_data[::-1]
        
        return reversed_data

    @staticmethod
    def postprocess_data_from_decryption(encoded_data: bytes) -> str:
        """
        Reverse the enhanced preprocessing.
        """
        import zlib
        import base64
        
        base64_data = encoded_data[::-1]
        
        xored_data = base64.b64decode(base64_data)
        
        xor_key = "L{ofT/r8tOJp".encode('utf-8')
        compressed_data = bytes(a ^ b for a, b in zip(xored_data, xor_key * (len(xored_data) // len(xor_key) + 1)))
        
        wrapped_data = zlib.decompress(compressed_data)
        
        fake_header = "MY_HEADER_v1.0_".encode('utf-8')
        fake_footer = "_END_DATA".encode('utf-8')
        data_bytes = wrapped_data[len(fake_header):-len(fake_footer)]
        
        return data_bytes.decode('utf-8')

    @staticmethod
    def contains_emoji(text):
        """Check if text contains any emoji characters."""
        if not text:
            return False
            
        # First check if any character is in our whitelist
        for char in text:
            if char in Utils.VALID_FILENAME_CHARS:
                continue
            # If not in whitelist, check if it's an emoji
            if Utils.EMOJI_PATTERN.search(char):
                logger.info(f"Found emoji in text: {text}")
                return True
        return False

    @staticmethod
    def clean_emoji(text):
        """Remove emoji characters from text and replace with [emoji] placeholder."""
        if Utils.contains_emoji(text):
            cleaned = Utils.EMOJI_PATTERN.sub("[emoji]", text)
            logger.info(f"Cleaned emoji from text: {text} -> {cleaned}")
            return cleaned
        return text

    @staticmethod
    def count_cjk_characters(text):
        """
        Count the number of CJK characters in the given text.
        
        Args:
            text: The text to analyze
            
        Returns:
            tuple: (total_cjk_chars, dict) where dict contains counts for each script:
                  {
                      'chinese': count,
                      'japanese': count,
                      'korean': count
                  }
                  
        Note:
            CJK characters include:
            - Chinese (Han): \u4e00-\u9fff
            - Japanese (Hiragana): \u3040-\u309f
            - Japanese (Katakana): \u30a0-\u30ff
            - Korean (Hangul): \uac00-\ud7af
        """
        if not text:
            return 0, {'chinese': 0, 'japanese': 0, 'korean': 0}
            
        script_counts = {
            'chinese': 0,
            'japanese': 0,
            'korean': 0
        }
        
        for c in text:
            if '\u4e00' <= c <= '\u9fff':  # Chinese
                script_counts['chinese'] += 1
            elif '\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff':  # Japanese
                script_counts['japanese'] += 1
            elif '\uac00' <= c <= '\ud7af':  # Korean
                script_counts['korean'] += 1
                
        total_cjk = sum(script_counts.values())
        return total_cjk, script_counts

    @staticmethod
    def get_cjk_character_ratio(text, threshold_percentage=None):
        """
        Calculate the ratio of CJK characters in the given text.
        
        Args:
            text: The text to analyze
            threshold_percentage: Optional percentage threshold (0-100). If provided,
                                returns True if the ratio exceeds this threshold.
        
        Returns:
            If threshold_percentage is None:
                float: Ratio of CJK characters (0.0 to 1.0)
            If threshold_percentage is provided:
                bool: True if ratio exceeds threshold, False otherwise
                
        Note:
            CJK characters include:
            - Chinese (Han): \u4e00-\u9fff
            - Japanese (Hiragana): \u3040-\u309f
            - Japanese (Katakana): \u30a0-\u30ff
            - Korean (Hangul): \uac00-\ud7af
        """
        if not text:
            return 0.0 if threshold_percentage is None else False
            
        cjk_char_count, _ = Utils.count_cjk_characters(text)
        ratio = cjk_char_count / len(text)
        
        if threshold_percentage is not None:
            return ratio > (threshold_percentage / 100.0)
            
        return ratio

    @staticmethod
    def is_valid_filename(filename):
        # Implement the logic to check if a filename is valid
        # This is a placeholder and should be replaced with the actual implementation
        return True

from enum import Enum

class ModifierKey(Enum):
    SHIFT = 0x1
    CAPS_LOCK = 0x2
    CTRL = 0x4
    ALT = 0x20000
