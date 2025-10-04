#
# safetriggers
#
# A TOOL TO HELP USERS OF AI MANAGE THEIR .safetensors LowRankAdaptors (LoRAs)
#
# VERSION
__version_info__ = ('2025','03','16')
#
# BY
# DAVROS***  --  NOTE: Original author's name modified slightly.
#
#
# =========
# RATIONALE
# =========
#
# "AI txt2img requires the use of .safetensors LoRAs and often these are huge files containing vast amounts
# of data in a variety of forms, the result of expensive training on a number of tagged images.
#
# Once installed, a LoRA needs to be 'triggered' by key words and phrases in a prompt to be activated and
# its utility realized.
#
# When issued, the user can often recall or simply look-up the developer's intentions and description of the
# LoRA but if orphaned or installed using an unregocnizable name, it's intent and usage must be teased from
# it's internal data, often involving the scanning of a huge unmanageable text file, the ".safetensors" file
# representing the LoRA.
#
# This tool was developed to simplify that task and make a corresponding ".safetriggers" file that might
# conveniently reside alongside the ".safetensors" file, in a simple standard JSON format, listing the
# tags, trigger-words and trigger-phrases baked in when training the LoRA from tagged source images by
# the developer.
#
# I wrote this for myself as I had a collection of unusable, orphaned or unreconizable LoRAs downloaded
# for local image creation and hadn't a clue how to use some of them and no time nor patience to go
# searching for them online, if indeed that was even an option in this fast-moving field of AI.
#
# A file alongside the "'safetensors" file called by the same name but with the ".safetriggers" extension
# seemed an ideal solution to this niggling problem for me and I hope you find it useful too."
#     DAVROS***, 2025Mar08
#
#
# VERSIONS
# 2025Mar08 - INITIAL VERSION BY DAVROS*** - LINUX, TESTED ON UBUNTU SERVER 24.10
#
# 2025Mar11 - Added -allloras so ALL LoRAs in a path can be processed
#             Added ANOTHER LoRA format
#             Bug Fixes & Typos
#
# 2025Mar12 - Added better code generalization for additional LoRA formats
#             Added RegularExpression REGEX code for complex in-data pattern-matching
#             Caught More Exceptions
#             Bug Fixes & Typos
#
# 2025Mar13 - Added -safetriggers so .safetriggers files can be read and printed on-screen
#             Added WARNING if a LoRA contains 'NO TAGS'
#             Now handles LoRAs with TAGS containing characters that cannot be sorted by saving UNSORTED TAGS instead
#             Typos
#
# 2025Mar16 - Added print() to indicate STARTING TO ANALYSE <some file or other>
#             Improved 'tag_frequency' parsing
#             Tidied up CLI arguments and added SINGLE CHARACTER alternatives on a SINGLE 'dash'
#             Added --combine to combines all 'tag_frequency' groups in the META_DATA into a SINGLE TAG DICT
#
#
# LICENSE
# "Let do what thou wilt be the whole of The Law"
#
#
__version__ = '-'.join(__version_info__)


import os
import os.path
import argparse
import mmap
import re
import json
import pprint
import collections


#
# COLORED TEXT ON CLI
#
FAIL, BOLD, ENDC = '\033[91m', '\033[1m', '\033[0m'


#
# SEARCH FOR ANY TAG DATA IN LoRA
#
# Q. DOES LoRA CONTAIN ANY TAG DATA?
#
def search_lora_for_any_tags(lora_name):
    # SEARCHING FILE AS MEMORY-EFFICIENT DATA BYTE ARRAY
    with open(lora_name, "rb") as f_in, mmap.mmap(f_in.fileno(), 0, access=mmap.ACCESS_READ) as s:
        # GET START OF TAG DATA
        tagsat = s.find(b"tag_")
        return (tagsat != -1)


#
# SEARCH FOR TAG DATA IN LoRA
#
# FORMAT A; FIND DATA DELIMITED BY PAIRS OF KNOWN START AND END MARKERS
#
# RETURNS;
# ON ERROR,   NONE,0
# ON SUCCESS, POSITION OF START OF TAGS AND TRIGGERS AND LENGTH OF THAT DATA
#
def search_lora_for_tags_A(lora_name, start_markers, end_markers):
    # SEARCHING FILE AS MEMORY-EFFICIENT DATA BYTE ARRAY
    with open(lora_name, "rb") as f_in, mmap.mmap(f_in.fileno(), 0, access=mmap.ACCESS_READ) as s:
        for s_m in start_markers:
            # GET START OF TAG DATA
            data_startat = s.find(s_m)
            if data_startat != -1:
                # POSITION POINTS TO START OF START MARKER SO MOVE IT TO JUST AFTER START MARKER,
                # PRESERVING CURLY-BRACKETS AROUND DATA
                data_startat += len(s_m)

                # GET END OF TAG DATA, BEGIN SEARCH AFTER KNOWN START POSITION
                for e_m in end_markers:
                    data_endat = s.find(e_m, data_startat)
                    if data_endat != -1:
                        # CALC LENGTH OF TAGS DATA
                        #print(f"FORMAT:A; tags @ {BOLD}{data_startat}{ENDC} to {BOLD}{data_endat}{ENDC}")

                        # POSITION POINTS TO END OF END MARKER SO MOVE IT TO JUST AFTER END MARKER,
                        # PRESERVING CURLY-BRACKETS AROUND DATA
                        data_len = data_endat - data_startat
                        if data_len > 0:
                            return data_startat,data_len

                    # NOT FOUND, TRY NEXT END MARKER

            # NOT FOUND, TRY NEXT START MARKER

        # EXHAUSTED ALL markers_startend AND DATA NOT FOUND
        print(f"{FAIL}TAGS UNREADABLE USING FORMAT:A{ENDC}; \
                 LoRA not encoded using FORMAT:A!")
        return None,0


#
# SEARCH FOR TAG DATA IN LoRA
#
# FORMAT B; SEARCH FOR START OF DATA USING KNOWN START MARKER THEN FIND ITS END AT NEXT '}'
#
# RETURNS;
# ON ERROR,   NONE,0
# ON SUCCESS, POSITION OF START OF TAGS AND TRIGGERS AND LENGTH OF THAT DATA
#
def search_lora_for_tags_B(lora_name, start_markers):
    # SEARCHING FILE AS MEMORY-EFFICIENT DATA BYTE ARRAY
    with open(lora_name, "rb") as f_in, mmap.mmap(f_in.fileno(), 0, access=mmap.ACCESS_READ) as s:
        for s_m in start_markers:
            # GET START OF TAG DATA
            data_startat = s.find(s_m)
            if data_startat != -1:
                # POSITION POINTS TO START OF START MARKER SO MOVE IT TO JUST AFTER START MARKER,
                # PRESERVING CURLY-BRACKETS AROUND DATA
                data_startat += len(s_m)

                # GET END OF TAG DATA, BEGIN SEARCH AFTER KNOWN START POSITION
                data_endat = s.find(b'}', data_startat)
                if data_endat != -1:
                    # CALC LENGTH OF TAGS DATA
                    #print(f"FORMAT:B; tags @ {BOLD}{data_startat}{ENDC} to {BOLD}{data_endat}{ENDC}")

                    # POSITION POINTS TO END OF END MARKER SO MOVE IT TO JUST AFTER SINGLE-CHARACTER END MARKER,
                    # PRESERVING CURLY-BRACKETS AROUND DATA
                    data_len = (data_endat + 1) - data_startat
                    if data_len > 0:
                        return data_startat,data_len

            # NOT FOUND, TRY NEXT MARKER

        # EXHAUSTED ALL markers_startend AND DATA NOT FOUND
        print(f"{FAIL}TAGS UNREADABLE USING FORMAT:B{ENDC}; \
                 LoRA not encoded using FORMAT:B!")
        return None,0


#
# SEARCH LORA FOR START AND END MARKERS FOR TAGS & TRIGGERS, BEGINNING AT search_from
#
# FORMAT C; SEARCH FOR START OF DATA USING START MARKER, THEN SKIP TO NEXT '{' THEN FIND ITS END AT NEXT '}'
#
# RETURNS;
# ON ERROR,   NONE,0
# ON SUCCESS, POSITION OF START OF TAGS AND TRIGGERS AND LENGTH OF THAT DATA
#
def search_lora_for_tags_C(lora_name, start_markers, search_from):
    # SEARCHING FILE AS MEMORY-EFFICIENT DATA BYTE ARRAY
    with open(lora_name, "rb") as f_in, mmap.mmap(f_in.fileno(), 0, access=mmap.ACCESS_READ) as s:
        for s_m in start_markers:
            # GET START OF TAG DATA
            data_nr_startat = s.find(s_m, search_from)
            if data_nr_startat != -1:
                # POSITION POINTS TO START OF START MARKER SO MOVE IT TO JUST AFTER START MARKER
                data_nr_startat += len(s_m)

                # FIND REAL START OF NONSENSE, BEGIN SEARCH AFTER KNOWN NR START POSITION
                data_nr_startat = s.find(b'{', data_nr_startat)
                if data_nr_startat != -1:
                    # POSITION POINTS TO FIRST OPEN CURLY-BRACKET, A SINGLE CHARACTER AROUND NONSENSE PRECEDING DATA,
                    # SO START SEARCH PAST IT
                    data_nr_startat += 1

                    # SKIP NONSENSE TO FIND REAL START OF DATA, BEGIN SEARCH AFTER KNOWN NR START POSITION
                    data_startat = s.find(b'{', data_nr_startat)
                    if data_startat != -1:
                        # POSITION POINTS TO SECOND OPEN CURLY-BRACKET AT START OF DATA,
                        # PRESERVING CURLY-BRACKETS AROUND DATA

                        # GET END OF TAG DATA, BEGIN SEARCH AFTER KNOWN START POSITION
                        data_endat = s.find(b'}', data_startat)
                        if data_endat != -1:
                            # CALC LENGTH OF TAGS DATA
                            #print(f"FORMAT:A; tags @ {BOLD}{data_startat}{ENDC} to {BOLD}{data_endat}{ENDC}")

                            # POSITION POINTS TO END OF END MARKER SO MOVE IT TO JUST AFTER SINGLE-CHARACTER END MARKER,
                            # PRESERVING CURLY-BRACKETS AROUND DATA
                            data_len = (data_endat + 1) - data_startat
                            if data_len > 0:
                                return data_startat,data_len

            # NOT FOUND, TRY NEXT MARKER

        # EXHAUSTED ALL markers_startend AND DATA NOT FOUND
        print(f"{FAIL}TAGS UNREADABLE USING FORMAT:C{ENDC}; \
                 LoRA not encoded using FORMAT:C!")
        return None,0


#
# READ DATA FOR TAGS AND TRIGGERS FROM LORA
#
# RETURNS;
# ON ERROR,   NONE
# ON SUCCESS, DATA CONTAINING TAGS AND TRIGGERS
#
def read_trigger_data_from_lora(format, lora_name, data_start, data_len):
    # READING FILE AS MEMORY-EFFICIENT DATA BYTE ARRAY
    with open(lora_name, "rb") as f_in, mmap.mmap(f_in.fileno(), 0, access=mmap.ACCESS_READ) as s:
        # SEEK TO POSITION AFTER START MARKER...
        s.seek(data_start)

        # ... THEN READ UPTO END MARKER, AS A SIMPLE STRING
        # NOW IT IS SMALL ENOUGH TO BE HANDLED *AND* SHOULD BE IN A SIMPLER FORM FOR JSON PARSING AND HUMAN READABILITY
        try:
            #return s.read(data_len).decode()
            return s.read(data_len)
        except:
            print(f"{FAIL}TRIGGER DATA UNREADABLE USING FORMAT:{format}{ENDC}; \
                     LoRA not encoded using FORMAT:{format}!")
            return None


#
# TEASE TAGS & TRIGGERS FROM TRIGGER DATA TO CREATE A JSON COMPATIBLE DICTIONARY
#
# MORE VERSIONS OF LoRAs MAY EXIST AND WILL HAVE TO BE DECODED IN LATER VERSIONS OF THIS TOOL
#
# PARSE TAG & TRIGGER DATA USING A VARIETY OF METHODS
#
# RETURNS;
# ON ERROR,   NONE
# ON SUCCESS, dictionaty of tags & triggers
#
def parse_trigger_data(trigger_data):
    # TRY TO PARSE TRIGGER DATA INTO A DICTIONARY IN A VARIETY OF WAYS,
    # BETWEEN FIXING IT AND TRYING AGAIN UNTIL EITHER SUCCESS, HEAT-DEATH OF THE KNOWN UNIVERSE OR GIVING UP

    # FIRST TRY
    try:
        # WILL IT PARSE? "ARE WE THERE YET?"
        #
        # RAW ORIGINAL
        #
        d = json.loads(trigger_data)
        #print(f"{BOLD}json.load{ENDC}; \
        #         Encoded as {BOLD}RAW{ENDC};\n{trigger_data}\n")
        #
        print(f"{BOLD}TRIGGER_FORMAT{ENDC}; \
                 SUCCESS: RAW")
        return d

    except:
        #print(f"{FAIL}json.load FAILURE{ENDC}; \
        #         Encoded as {BOLD}RAW{ENDC};\n{trigger_data}\n")
        #
        print(f"{FAIL}TRIGGER_FORMAT{ENDC}; \
                 FAILURE: RAW")

        # FIX DATA AND TRY AGAIN
        try:
            # WILL IT PARSE? "ARE WE THERE YET?"
            #
            # PROBLEM TEXT EXAMPLE; { RIOT OF BACKSLASHES }
            #
            # SOLUTION;             SIMPLY REMOVE *ALL* BACKSLASHES
            #
            t_data = trigger_data.replace(b'\\', b"")
            #print(f"{BOLD}json.load{ENDC}; \
            #         Encoded as {BOLD}BKS PURGED{ENDC};\n{t_data}\n")
            #
            d = json.loads(t_data)
            print(f"{BOLD}TRIGGER_FORMAT{ENDC}; \
                     SUCCESS: BACKSLASHES PURGED")
            return d

        except:
            #print(f"{FAIL}json.load FAILURE{ENDC}; \
            #         Encoded as {BOLD}BKS PURGED{ENDC};\n{t_data}\n")
            #
            print(f"{FAIL}TRIGGER_FORMAT{ENDC}; \
                     FAILURE: BACKSLASHES PURGED")

            # FIX DATA AND TRY AGAIN
            try:
                # WILL IT PARSE? "ARE WE THERE YET?"
                #
                # PROBLEM TEXT EXAMPLE; {\\"a\\":1, \\"b\\":2, \\"c\\":3}
                #
                # SOLUTION;             ALL DOUBLE-BACKSLASHES CONVERTED TO SINGLE-BACKSLASHES
                #
                t_data = trigger_data.replace(b'\\\\', b"\\")
                #print(f"{FAIL}json.load{ENDC}; \
                #         Encoded as {BOLD}OVER-ENTHUSIASTIC BKS PURGED{ENDC};\n{t_data}\n")
                #
                d = json.loads(t_data)
                print(f"{BOLD}TRIGGER_FORMAT{ENDC}; \
                         SUCCESS: OVER-ENTHUSIASTIC BACKSLASHES PURGED")
                return d

            except:
                #print(f"{FAIL}json.load FAILURE{ENDC}; \
                #         Encoded as {BOLD}OVER-ENTHUSIASTIC BKS PURGED{ENDC};\n{t_data}\n")
                #
                print(f"{FAIL}TRIGGER_FORMAT{ENDC}; \
                         FAILURE: OVER-ENTHUSIASTIC BACKSLASHES PURGED")

                # FIX DATA AND TRY AGAIN
                try:
                    # WILL IT PARSE? "ARE WE THERE YET?"
                    #
                    # PROBLEM TEXT EXAMPLE; {\"a a\":1, \"b \\\"ddd\\\" b\":2, \"c c\":3}
                    #
                    # SOLUTION;             TRIPLE-BACKSLASHES-DOUBLE-QUOTE CONVERTED TO A SINGLE-QUOTE TO PRESERVE MEANING
                    #                       THEN
                    #                       ALL SINGLE BACKSLASHES REMOVED
                    #
                    re_text = trigger_data.replace(b'\\\\\\\"', b"\'")
                    t_data = re_text.replace(b'\\', b"")
                    #print(f"{BOLD}json.load{ENDC}; \
                    #         Encoded as {BOLD}I-S BKS TRIMMED + O-S BKS PURGED{ENDC};\n{t_data}\n")
                    #
                    d = json.loads(t_data)
                    print(f"{BOLD}TRIGGER_FORMAT{ENDC}; \
                             SUCCESS: IN-STRING BACKSLASHES TRIMMED + OUT-STRING BACKSLASHES PURGED")
                    return d

                except:
                    #print(f"{FAIL}json.load FAILURE{ENDC}; \
                    #         Encoded as {BOLD}I-S BKS TRIMMED + O-S BKS PURGED{ENDC};\n{t_data}\n")
                    #
                    print(f"{FAIL}TRIGGER_FORMAT{ENDC}; \
                             FAILURE: IN-STRING BACKSLASHES TRIMMED + OUT-STRING BACKSLASHES PURGED")

                    # FIX DATA AND TRY AGAIN
                    try:
                        # WILL IT PARSE? "ARE WE THERE YET?"
                        #
                        # REMOVE ALL BACKSLASHES AND PUT EACH ENTRY ON A SEPARATE LINE
                        #
                        t_data = trigger_data.replace(b'\\', b"").replace(b',', b",\n")
                        #print(f"{BOLD}json.load{ENDC}; \
                        #         Encoded as {BOLD}BKS PURGE + COMMA{ENDC};\n{t_data}\n")
                        #
                        d = json.loads(t_data)
                        print(f"{BOLD}TRIGGER_FORMAT{ENDC}; \
                                 SUCCESS: BACKSLASH PURGE PLUS COMMA PRETTIFICATION")
                        return d

                    except:
                        #print(f"{FAIL}json.load FAILURE{ENDC}; \
                        #         Encoded as {BOLD}BKS PURGE + COMMA{ENDC};\n{t_data}\n")
                        #
                        print(f"{FAIL}TRIGGER_FORMAT{ENDC}; \
                                 FAILURE: BACKSLASH PURGE PLUS COMMA PRETTIFICATION")

                        # NOPE!
                        #
                        # DISPLAY TRIGGER/TAGS ON-SCREEN TO TRY TO UNDERSTAND FORMAT
                        print(f"{FAIL}TRIGGER_FORMAT UNRECOGNIZED{ENDC}; \
                                 LoRA triggers encoded as;\n{trigger_data}\n")
                        return None

    #
    # WHAT I HAVE LEARNED IS THAT BACKSLASHES ARE TYPICALLY THE ISSUE RE. DECYPHERING LoRAs
    #


#
# TEASE TAGS & TRIGGERS FROM .safetensors OF LoRA FILE TO CREATE A DICTIONARY
#
# LoRA CAN BE SEARCHED FOR MULTIPLE SETS OF TAGS/TRIGGERS AND THESE CAN BE OPTIONALLY '--combine'D
# INTO A SINGLE DICTIONARY
#
# MORE VERSIONS OF LoRAs MAY EXIST WITH DIFFERENT ENCODING AND 
# THESE WILL HAVE TO BE DECODED IN LATER VERSIONS OF THIS TOOL,
# BUT FOR NOW THE MOST COMMON FORMS ARE READ AND DECODED
#
# PARSE TAG & TRIGGER DATA FROM LoRA USING A VARIETY OF METHODS
#
# RETURNS;
# ON ERROR,   NONE
# ON SUCCESS, dictionaty of tags & triggers
#
def read_triggers_from_lora(lora_name, args):
    # DOES THE LoRA CONTAIN ANY REFERENCE TO TAGS?
    if not search_lora_for_any_tags(lora_name):
        # CANNOT FIND DATA IN ANY KNOWN FORMAT
        print(f"{FAIL}NO TAGS STORED IN LoRA{ENDC}; \
                 LoRA contains {BOLD}NO TAGS{ENDC} so {BOLD}NO TRIGGER-WORDS{ENDC} & {BOLD}NO TRIGGER-PHRASES{ENDC}!")
        return None

    #
    # TO JSON DECODE, TAGS MUST BE ENCLOSED BY CURLY BRACKETS
    # SO MARKERS SHOULD BE CRAFTED SO AS TO LEAVE THOSE AROUND THE TAG LIST
    #

    # TO FIND TRIGGER/TAGS IN META_DATA IN LoRA, IN BYTE ARRAY FORM,
    # USE THESE MARKERS AND THE APPROPRIATE SEARCH TECHNIQUE TO SKIP OVER UNWANTED DATA

    #
    # FIND TRIGGER DATA, MOVING THROUGH DIFFERENT APPROACHES ON FAILURE UNTIL ALL ARE TRIED
    #

    # TRY FORMAT; IMPROVED ALPHA
    format = "IMPROVED ALPHA"
    #
    # SOME ATYPICAL NONSENSE IS USUALLY BETWEEN THE '*tag_frequency' PART AND START OF ANY DATA
    #   eg. \"ss_tag_frequency\":\"{\"XXXmongooseArsemonkeyBridgetWarble ...\": {" AND ONLY THEN THE TAGS DATA!
    # SO THIS TRIPE NEEDS TO BE SKIPPED OVER, THEN THE NEXT '{', TO THE NEXT '{' AND THE START OF THE DATA
    # AND ONLY THEN DO WE FIND THE DATA'S END BY FINDING THE NEXT '}'
    #
    markers_start = { b'\"tag_frequency' , b'\"ss_tag_frequency' }
    #
    if not args.combine:
        #
        # SINGLE DICTIONARY OF TRIGGERS READ FROM LoRA
        #

        # READ FIRST SET OF TAGS FROM LoRA, STARTING SEARCH AT BEGINNING OF LoRA
        tags_startat,tags_len = search_lora_for_tags_C(lora_name, markers_start, 0)
        if not tags_startat or (tags_len == 0):
            # CANNOT FIND ANY DATA IN LoRA
            print(f"{FAIL}TRIGGER DATA MISSING{ENDC}; \
                     LoRA encoded so as to include NO TAGS, NO TRIGGER-WORDS nor any TRIGGER-PHRASES! \
                     Contact creator of LoRA for details on usage...")
            return None

        # READ TRIGGER DATA
        trigger_data = read_trigger_data_from_lora(format, lora_name, tags_startat, tags_len)
        if not trigger_data:
            # CANNOT FIND DATA IN ANY KNOWN FORMAT
            print(f"{FAIL}TRIGGER DATA UNREADABLE{ENDC}; \
                     Unable to READ data from LoRA!")
            return None

        #
        # AT THIS POINT, TRIGGER DATA SHOULD BE IN SOME VARIATION OF A COMMA-SEPARATED TEXT FORMAT;
        # eg. {"<trigger>":<number>, ...}
        #
        # TRY TO DECYPHER IT, READY FOR DISPLAY/OUTPUT
        #
        single_trigger_dictionary = parse_trigger_data(trigger_data)
        return single_trigger_dictionary

    else:
        #
        # ALL DICTIONARIES OF TRIGGERS READ FROM LoRA
        #

        # READ ALL SETS OF TAGS FROM LoRA AND COMBINE THEM
        combined_trigger_dict = None
        search_from           = 0
        while True:
            # READ SET OF TAGS FROM LoRA, STARTING SEARCH AT search_from
            tags_startat,tags_len = search_lora_for_tags_C(lora_name, markers_start, search_from)
            if not tags_startat or (tags_len == 0):
                #print(f"No TAG-FREQUENCY data in {BOLD}{lora_name}{ENDC} after pos({BOLD}{search_from}{ENDC})")
                break

            # READ TRIGGER DATA
            trigger_data = read_trigger_data_from_lora(format, lora_name, tags_startat, tags_len)
            if not trigger_data:
                # CANNOT FIND DATA IN ANY KNOWN FORMAT
                print(f"{FAIL}TRIGGER DATA UNREADABLE{ENDC}; \
                         Unable to READ data from LoRA!")
                return None

            #
            # AT THIS POINT, TRIGGER DATA SHOULD BE IN SOME VARIATION OF A COMMA-SEPARATED TEXT FORMAT;
            # eg. {"<trigger>":<number>, ...}
            #
            # TRY TO DECYPHER IT, READY FOR DISPLAY/OUTPUT
            #
            trigger_dict = parse_trigger_data(trigger_data)
            if not trigger_dict:
                # CANNOT FIND DATA IN ANY KNOWN FORMAT
                print(f"{FAIL}TRIGGER DATA UNRECOGNIZABLE{ENDC}; \
                         Unable to PARSE data from LoRA!")
                return None

            # COMBINE NEW TAG_FREQUENCY DATA WITH EXISTING DICTIONARY
            combined_trigger_dict = trigger_dict if not combined_trigger_dict else (combined_trigger_dict | trigger_dict)

            # SKIP THIS DATA AND SEARCH AGAIN FROM AFTER IT
            search_from = tags_startat + tags_len

            #
            # REPEAT UNTIL DECODED ALL TAG-FREQUENCY GROUPS IN LoRA
            #

        # FINISHED READING ALL TAG-FREQUENCIES FROM LoRA
        return combined_trigger_dict


#
# TEASE TAGS & TRIGGERS FROM .safetriggers OF LoRA TRIGGERS FILE TO CREATE A DICTIONARY
#
# RETURNS;
# ON ERROR,   NONE
# ON SUCCESS, dictionaty of tags & triggers
#
def read_triggers_from_safetriggers(safetriggers_name):
    # READ THE .safetriggers FILE AND PARSE IT INTO A DICTIONARY OF TRIGGERS
    with open(safetriggers_name, "r") as f_in:
        try:
            data = f_in.read()
            parsed_trigger_data = json.loads(data)
        except:
            parsed_trigger_data = None

        if not parsed_trigger_data:
            print(f"{FAIL}LoRA SAFETRIGGERS UNREADABLE{ENDC}; \
                    {FAIL}{safetriggers_name}{ENDC}; LoRA SAFETRIGGERS FILE CORRUPTED? OUTDATED FORMAT? REMAKE IT")
            return None

        return parsed_trigger_data


#
# SHOW TRIGGERS ON-SCREEN
#
def display_triggers(file_name, triggers, args):
    # DISPLAY TRIGGERS FOR LoRA ON SCREEN?
    print(f"{BOLD}safetriggers{ENDC}; \
            {BOLD}{file_name}{ENDC} trigger words and phrases are;\n")

    # DISPLAY PARSED TRIGGERS
    # SORTED IN TERMS OF DESCENDING OCCURRENCE WITH MOST COMMON TAGS LISTED FIRST IN 'PRETTY' FORM ON-SCREEN
    try:
        sorted_triggers = collections.OrderedDict(sorted(triggers.items(), key=lambda x: x[1], reverse=True))
        try:
            skip_minimum_check = len(sorted_triggers) < 2
            skip_count_check = args.triggercount < 1
            i = 0
            for trigger, count in sorted_triggers.items():
                i += 1
                if (not skip_count_check and i > args.triggercount):
                    print(f"etc...")
                    break
                if count < args.triggerminimum:
                    print(f"etc... (lower than minimum count {args.triggerminimum})")
                    break
                print(f"{count}\t{BOLD}{trigger}{ENDC}")
            # pprint.pprint(sorted_triggers, width=150)
        except:
            print(f"{FAIL}Print FAILURE{ENDC}; \
                     Unable to Print this text since LoRA Tags may contain invalid characters sequences!")
            print(f"{BOLD}Print FAILURE{ENDC}; \
                     Contact Python Library Devs for more details...")

    except:
        print(f"{FAIL}SORTING TRIGGERS FAILED{ENDC}; \
                 Unable to SORT TRIGGERS since LoRA Tags may contain invalid characters sequences as keys!")
        print(f"{BOLD}FALLBACK TO UNSORTED{ENDC}; \
                 SORRY! Here are the {BOLD}UNSORTED{ENDC} trigger words and phrases instead;\n{triggers}\n")

    print("")


#
# PROCESS DICTIONARY CONTAINING TAGS & TRIGGERS
# THEN OPTIONALLY WRITE THESE INTO A .safetriggers FILE OR DISPLAY THEM ON-SCREEN
#
def process_triggers(lora_name, triggers, args):
    # DISPLAY TRIGGERS FOR LoRA ON SCREEN?
    if args.display:
        display_triggers(lora_name, triggers, args)

    # MAKE .safetriggers FILE TO ACCOMPANY LoRA?
    if args.mksafetriggers:
        # DEFINE FULL FILENAME OF LoRA
        triggers_name = lora_name.replace(".safetensors",".safetriggers")

        # .safetriggers FILE EXISTS?
        if os.path.isfile(triggers_name):
            print(f"Overwriting {BOLD}{triggers_name}{ENDC}...")

        # WRITE PARSED TRIGGERS
        # SORTED IN TERMS OF DESCENDING OCCURRENCE WITH MOST COMMON TAGS LISTED FIRST
        # AS JSON FORMAT FILE
        with open(triggers_name, 'w') as f_out:
            try:
                sorted_triggers = collections.OrderedDict(sorted(triggers.items(), key=lambda x: x[1], reverse=True))
                try:
                    json.dump(sorted_triggers, f_out, separators=(',' , ':'))
                except:
                    print(f"{FAIL}JSON dump() FAILURE{ENDC}; \
                             Unable to JSON.dump this text since LoRA Tags may contain invalid characters sequences!")
                    print(f"{BOLD}JSON dump() FAILURE{ENDC}; \
                             Contact Python Library Devs for more details...")

                    # UNABLE TO PROCEED SINCE MAKING .safetriggers FAILED
                    print(f"{FAIL}PROBLEM WHILE CREATING .safetriggers FILE{ENDC}; \
                             Issue occured while creating {BOLD}{triggers_name}{ENDC} for {BOLD}{lora_name}{ENDC}")
                    return

                print(f"Created {BOLD}{triggers_name}{ENDC} for {BOLD}{lora_name}{ENDC}")

            except:
                print(f"{FAIL}SORTING TRIGGERS FAILED{ENDC}; \
                         Unable to SORT TRIGGERS since LoRA Tags may contain invalid characters sequences as keys!")
                print(f"{BOLD}FALLBACK TO UNSORTED{ENDC}; \
                         SORRY! Presenting the {BOLD}UNSORTED{ENDC} trigger words and phrases instead...")

                try:
                    json.dump(triggers, f_out, separators=(',' , ':'))
                except:
                    print(f"{FAIL}JSON dump() FAILURE{ENDC}; \
                             Unable to JSON.dump this text since LoRA Tags may contain invalid characters sequences!")
                    print(f"{BOLD}JSON dump() FAILURE{ENDC}; \
                             Contact Python Library Devs for more details...")

                    # UNABLE TO PROCEED SINCE MAKING .safetriggers FAILED
                    print(f"{FAIL}PROBLEM WHILE CREATING .safetriggers FILE{ENDC}; \
                             Issue occured while creating {BOLD}{triggers_name}{ENDC} for {BOLD}{lora_name}{ENDC}")
                    return

                print(f"Created {BOLD}UNSORTED{ENDC} {BOLD}{triggers_name}{ENDC} for {BOLD}{lora_name}{ENDC}")


#
# READ LoRA (.safetensors) FILE AND READ TRIGGERS FROM IT
#
# RETURNS;
# ON ERROR,   False
# ON SUCCESS, True
#
def read_lora(lora_name, args):
    triggers = read_triggers_from_lora(lora_name, args=args)
    if not triggers or (len(triggers) == 0):
        # UNKNOWN LoRA FORMAT
        basename, _ = os.path.splitext(os.path.basename(lora_name))
        print(f"{FAIL}{basename} NOT SUPPORTED BY THIS VERSION{ENDC}; \
                LoRA (.safetensors) file contains tags & triggers in unrecognized format! \
                Check for NEWER version of {BOLD}safetriggers{ENDC} tool OR \
                LoRA may not contain any tag/trigger information from its creator, thus contacting them may be an option!")
        return False

    process_triggers(lora_name, triggers, args)
    return True


#
# READ LoRA TRIGGERS (.safetriggers) FILE AND READ TRIGGERS FROM IT
# THEN DISPLAY THEM ON-SCREEN
#
# RETURNS;
# ON ERROR,   False
# ON SUCCESS, True
#
def read_safetriggers(safetriggers_name, args):
    triggers = read_triggers_from_safetriggers(safetriggers_name)
    if not triggers or (len(triggers) == 0):
        # UNKNOWN LoRA FORMAT
        print(f"{FAIL}{safetriggers_name} CORRUPT OR NOT SUPPORTED BY THIS VERSION{ENDC}; \
                 LoRA Triggers (.safetriggers) file contains tags & triggers in unrecognized format! \
                 Consider REBUILDING LoRA Triggers (.safetriggers) file using {BOLD}--mksafetriggers{ENDC} option?")
        return False

    display_triggers(safetriggers_name, triggers, args)
    return True


def main():
    #
    # SAFETENSORS -> SAFETRIGGERS
    #

    # PARSE ARGUMENTS
    parser = argparse.ArgumentParser(description="Read/Display LoRA (.safetensors) trigger words and phrases; \
                                                display on screen or write a .safetriggers file using same name as LoRA, \
                                                NOTE. LoRAs ARE ONLY EVER READ AND ARE UNAFFECTED BY SAFETRIGGERS")

    parser.add_argument("--version",        "-v", action='version',                 version='%(prog)s {version}'.format(version=__version__))

    parser.add_argument("--lorapath",       "-p",                       default="./",  help="LoRA path; default is current directory")

    muex_g = parser.add_mutually_exclusive_group()
    muex_g.add_argument("--allloras",       "-a", action="store_true",  default=False, help="process ALL LoRAs on path; default False")
    muex_g.add_argument("--lora",           "-l",                       default="",    help="LoRA (.safetensors) file name WITHOUT .safetensors extension")
    muex_g.add_argument("--safetriggers",   "-s",                       default="",    help="LoRA Triggers (.safetriggers) file name \
                                                                                            WITHOUT .safetriggers extension")

    # experimental
    parser.add_argument("--combine",              action="store_false", default=True,  help="EXPERIMENTAL - combine ALL LoRA triggers found in the LoRA \
                                                                                            (may include tags from source images); default False")

    parser.add_argument("--display",        "-d", action="store_false", default=True,  help="display LoRA triggers on screen, \
                                                                                            in sorted JSON Format; default True")
    parser.add_argument("--mksafetriggers", "-m", action="store_true",  default=False, help="write LoRA triggers to .safetriggers file using same name, \
                                                                                            in sorted JSON Format; default False")
    muex_g.add_argument("--triggerminimum", "-n", type=int,             default=8,     help="minimum count per trigger to include in display and safetriggers file")
    muex_g.add_argument("--triggercount",   "-c", type=int,             default=10,    help="minimum count of triggers to include in display and safetriggers file")


    args = parser.parse_args()

    if   not args.lorapath:
        print(f"{FAIL}LoRa Path UNDEFINED!{ENDC} \
                {BOLD}--lorapath{ENDC} MUST be a valid path!")
        exit(1)

    elif not os.path.exists(args.lorapath):
        print(f"{FAIL}LoRa Path NOT FOUND!{ENDC}; \
                {BOLD}--lorapath{ENDC} MUST be a valid path!")
        exit(1)

    elif not args.allloras and (len(args.lora) == 0) and (len(args.safetriggers) == 0):
        print(f"{FAIL}File Name UNDEFINED!{ENDC}; \
                either using {BOLD}--lora{ENDC} a valid LoRA (.safetensors) file MUST be provided OR \
                        using {BOLD}--safetriggers{ENDC} a valid LoRA Triggers (.safetriggers) file MUST be provided OR \
                        using {BOLD}--allloras{ENDC} read ALL LoRA (.safetriggers) files on {BOLD}--lorapath{ENDC}!")
        exit(1)

    status_int = 0
    status = True

    # ONE LoRA OR ALL LoRAs ON PATH
    if args.allloras:
        # ANALYSE ALL LoRAs ON LoRA PATH

        # WALK ALL FILES ON PATH
        file_count = file_success = 0
        for root, dirs, files in os.walk(args.lorapath):
            for file in files:
                if file.endswith(".safetensors"):
                    # DEFINE FULL FILENAME OF LoRA
                    lora_name = os.path.join(root, file)

                    print(f"Analysing {BOLD}{file}{ENDC}...")

                    # READ LoRA
                    if not read_lora(lora_name, args):
                        print(f"Reading {BOLD}{lora_name}{ENDC} FAILED")
                    # INCREMENT FILE COUNTS
                    else:
                        file_success += 1 if status else 0

                    file_count   += 1

        # REPORT PERFORMANCE
        print(f"\n{BOLD}safetriggers{ENDC}; \
                LoRAs SUCCESSFULLY analysed: {BOLD}{file_success}{ENDC} out of {BOLD}{file_count}{ENDC}")

    elif args.lora and (len(args.lora) > 0):
        # ANALYSE ONE LoRA ON LoRA PATH

        # DEFINE SINGLE FULL FILENAME OF LoRA
        lora_name = f"{args.lorapath}/{args.lora}.safetensors"

        # LoRA (.safetensors) FILE EXISTS?
        if not os.path.isfile(lora_name):
            print(f"{FAIL}LoRA file not found!{ENDC}; \
                    {BOLD}--lora{ENDC} MUST be a valid LoRA file!")
            exit(1)

        print(f"Analysing {BOLD}{lora_name}{ENDC} ...\n")

        # READ LoRA
        if not read_lora(lora_name, args):
            print(f"Reading {BOLD}{lora_name}{ENDC} FAILED")
            status_int = 1

    elif args.safetriggers and (len(args.safetriggers) > 0):
        # READ AND DISPLAY ONE LoRA TRIGGERS FILE ON LoRA PATH

        # DEFINE SINGLE FULL FILENAME OF LoRA TRIGGERS
        safetriggers_name = f"{args.lorapath}/{args.safetriggers}.safetriggers"

        # LoRA TRIGGERS (.safetriggers) FILE EXISTS?
        if not os.path.isfile(safetriggers_name):
            print(f"{FAIL}LoRA TRIGGERS file not found!{ENDC}; \
                    {BOLD}--safetriggers{ENDC} MUST be a valid LoRA TRIGGERS file!")
            exit(1)

        print(f"Analysing {BOLD}{safetriggers_name}{ENDC} ...\n")

        # DISPLAY LoRA TRIGGERS
        if not read_safetriggers(safetriggers_name, args):
            print(f"Displaying {BOLD}{safetriggers_name}{ENDC} FAILED")
            status_int = 1

    else:
        print(f"{FAIL}safetriggers{ENDC}; \
                You didn't ask {BOLD}safetriggers{ENDC} to do anything.")
        status_int = 1

    exit(status_int)



if __name__ == "__main__":
    main()

