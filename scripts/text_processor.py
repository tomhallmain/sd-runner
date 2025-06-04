# text_processor.py
#
# This script processes text files to extract n-grams and word frequencies, which can be used to assist
# in manually building and maintaining the concept database for image diffusion prompt generation. By
# analyzing patterns in text, it helps identify common phrases and word combinations that might be
# worth adding to the concepts files. The script also handles special cases like contractions and
# non-English text to help ensure the concept database remains clean and relevant. The output can be
# used as a reference when manually editing the concepts files.
#
# To run this script from root directory:
#     python -m scripts.text_processor <directory> [--overwrite] [--unknown-words-dir <directory>] [--config <path>]
#
# The script requires a configuration file (default: text_processor_config.json in the script directory) with the following structure:
# {
#     "excluded_sections": {
#         "*": [  # Global sections that apply to all files
#             [start_line, end_line],
#             [start_line, end_line]
#         ],
#         "filename.txt": [  # Sections specific to one file
#             [start_line, end_line],
#             [start_line, end_line]
#         ]
#     },
#     "excluded_patterns": {
#         "*": [  # Global patterns that apply to all files
#             "pattern1",
#             "pattern2"
#         ],
#         "filename.txt": [  # Patterns specific to one file
#             "pattern3",
#             "pattern4"
#         ]
#     },
#     "remove_possessives": true,  # Whether to remove possessive 's from words
#     "special_cases": {  # Dictionary mapping special cases to their replacements
#         "'t": "it",
#         "th'": "the",
#         "i'": "in",
#         "t": "to",
#         "'r": "our"
#     }
# }
#
# Note: The "*" key can be used to specify sections and patterns that apply to all files.
# File-specific entries will be combined with global entries when processing each file.

from collections import defaultdict
from dataclasses import dataclass
import json
import os
import re
import statistics
from typing import List, Tuple, Dict, Any, Optional

import nltk
from nltk.tokenize import sent_tokenize
from sd_runner.concepts import Concepts

@dataclass
class Config:
    """Configuration for text processing."""
    path: str
    excluded_sections: Dict[str, List[Tuple[int, int]]]
    excluded_patterns: Dict[str, List[str]]
    is_default: bool = False
    # Text processing rules
    remove_possessives: bool = True  # Whether to remove possessive 's
    special_cases: Dict[str, str] = None  # Dictionary mapping special cases to their replacements

    def __post_init__(self):
        """Initialize default values for optional fields."""
        if self.special_cases is None:
            self.special_cases = {
                "'t": "it",
                "th'": "the",
                "i'": "in",
                "t": "to",
                "'r": "our"
            }

    @classmethod
    def from_json(cls, data: Dict[str, Any], path: str) -> 'Config':
        """Create a Config instance from JSON data."""
        return cls(
            path=path,
            excluded_sections={filename: [tuple(section) for section in sections] 
                             for filename, sections in data.get('excluded_sections', {}).items()},
            excluded_patterns=data.get('excluded_patterns', {}),
            remove_possessives=data.get('remove_possessives', True),
            special_cases=data.get('special_cases', None),
            is_default=False
        )

    def to_json(self) -> Dict[str, Any]:
        """Convert the Config instance to a JSON-serializable dictionary."""
        return {
            'excluded_sections': {filename: [list(section) for section in sections] 
                                for filename, sections in self.excluded_sections.items()},
            'excluded_patterns': self.excluded_patterns,
            'remove_possessives': self.remove_possessives,
            'special_cases': self.special_cases
        }

    def get_patterns_for_file(self, filename: str) -> List[str]:
        """Get all patterns that apply to a specific file."""
        patterns = []
        # Add global patterns (if any)
        patterns.extend(self.excluded_patterns.get('*', []))
        # Add file-specific patterns
        patterns.extend(self.excluded_patterns.get(filename, []))
        return patterns

    def get_sections_for_file(self, filename: str) -> List[Tuple[int, int]]:
        """Get all sections that apply to a specific file."""
        sections = []
        # Add global sections (if any)
        sections.extend(self.excluded_sections.get('*', []))
        # Add file-specific sections
        sections.extend(self.excluded_sections.get(filename, []))
        return sections

    @classmethod
    def create_default(cls) -> 'Config':
        """Create a default configuration."""
        return cls(
            excluded_sections={
                'henry-v_TXT_FolgerShakespeare.txt': [
                    (1838, 1931),  # French scene in Act 3, Scene 4
                    (3337, 3338),  # Additional French text
                    (3343, 3343),  # Additional French text
                    (3350, 3351),  # Additional French text
                    (3357, 3358),  # Additional French text
                    (3369, 3371),  # Additional French text
                    (3383, 3387),  # Additional French text
                    (3393, 3396),  # Additional French text
                    (3407, 3412),  # Additional French text
                    (3415, 3418),  # Additional French text
                    (3431, 3431),  # Additional French text
                    (3454, 3454),  # Additional French text
                ]
            },
            excluded_patterns={
                '*': [  # Global patterns that apply to all files
                    "Folger Shakespeare Library",
                    "https://shakespeare.folger.edu/",
                    "from FDT version",
                ]
            },
            path=os.path.join(os.path.dirname(__file__), 'text_processor_config.json'),
            remove_possessives=True,
            special_cases={
                "'t": "it",
                "th'": "the",
                "i'": "in",
                "t": "to",
                "'r": "our"
            },
            is_default=True
        )

def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from file or create default if not found."""
    if config_path is None:
        # Use default path in script directory
        config_path = os.path.join(os.path.dirname(__file__), 'text_processor_config.json')

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return Config.from_json(json.load(f), config_path)
        except Exception as e:
            raise Exception(f"Error loading config file: {str(e)}")
    else:
        # Create default config file
        config = Config.create_default()
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config.to_json(), f, indent=4)
            print(f"Created default configuration file at: {config_path}")
            print("\nPlease edit the configuration file to specify excluded sections and patterns.")
            print("The file has the following structure:")
            print("""
{
    "excluded_sections": {
        "*": [  # Global sections that apply to all files
            [start_line, end_line],
            [start_line, end_line]
        ],
        "filename.txt": [  # Sections specific to one file
            [start_line, end_line],
            [start_line, end_line]
        ]
    },
    "excluded_patterns": {
        "*": [  # Global patterns that apply to all files
            "pattern1",
            "pattern2"
        ],
        "filename.txt": [  # Patterns specific to one file
            "pattern3",
            "pattern4"
        ]
    },
    "remove_possessives": true,  # Whether to remove possessive 's from words
    "special_cases": {  # Dictionary mapping special cases to their replacements
        "'t": "it",
        "th'": "the",
        "i'": "in",
        "t": "to",
        "'r": "our"
    }
}

Note: The "*" key can be used to specify sections and patterns that apply to all files.
File-specific entries will be combined with global entries when processing each file.""")
        except Exception as e:
            print(f"Error creating config file: {str(e)}")
        return config

@dataclass
class ProcessedData:
    """Data class to hold processed text data."""
    bigrams: List[Tuple[Tuple[str, str], int]]
    trigrams: List[Tuple[Tuple[str, str, str], int]]
    words: List[Tuple[str, int]]
    unknown_words: List[Tuple[str, int]]
    valid_apostrophe_words: List[Tuple[str, int]]
    invalid_apostrophe_words: List[Tuple[str, int, str, int]]

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> 'ProcessedData':
        """Create a ProcessedData instance from JSON data."""
        return cls(
            bigrams=[(tuple(item['ngram'].split()), item['count']) for item in data['bigrams']],
            trigrams=[(tuple(item['ngram'].split()), item['count']) for item in data['trigrams']],
            words=[(item['word'], item['count']) for item in data['words']],
            unknown_words=[(item['word'], item['count']) for item in data.get('unknown_words', [])],
            valid_apostrophe_words=[(item['word'], item['count']) for item in data.get('valid_apostrophe_words', [])],
            invalid_apostrophe_words=[(item['word'], item['apostrophe_count'], item['without_apostrophe'], item['without_apostrophe_count']) 
                                    for item in data.get('invalid_apostrophe_words', [])]
        )

    def to_json(self) -> Dict[str, Any]:
        """Convert the ProcessedData instance to a JSON-serializable dictionary."""
        return {
            'words': [{'word': word, 'count': count} for word, count in self.words],
            'bigrams': [{'ngram': ' '.join(bigram), 'count': count} for bigram, count in self.bigrams],
            'trigrams': [{'ngram': ' '.join(trigram), 'count': count} for trigram, count in self.trigrams],
            'unknown_words': [{'word': word, 'count': count} for word, count in self.unknown_words],
            'valid_apostrophe_words': [{'word': word, 'count': count} for word, count in self.valid_apostrophe_words],
            'invalid_apostrophe_words': [{'word': word, 'apostrophe_count': apostrophe_count, 
                                        'without_apostrophe': without_apostrophe, 
                                        'without_apostrophe_count': without_apostrophe_count} 
                                       for word, apostrophe_count, without_apostrophe, without_apostrophe_count in self.invalid_apostrophe_words]
        }

def download_nltk_data():
    """Download required NLTK data."""
    nltk.download('punkt', quiet=True)

def is_valid_word(word: str) -> bool:
    """Check if word contains at least one alphabetic character and is not empty."""
    return word and any(c.isalpha() for c in word)

def process_possessives(word: str) -> str:
    """Remove possessive 's from words, except for 'it's'."""
    if word == "it's":
        return word
    if word.endswith("'s"):
        return word[:-2]
    return word

def calculate_statistics(data: List[Tuple[str, int]], name: str) -> None:
    """Calculate and print statistics for a given dataset."""
    if not data:
        return

    counts = [count for _, count in data]
    total = sum(counts)
    mean = statistics.mean(counts)
    median = statistics.median(counts)
    try:
        stdev = statistics.stdev(counts)
    except statistics.StatisticsError:
        stdev = 0

    # Calculate quartiles
    sorted_counts = sorted(counts)
    q1 = sorted_counts[len(sorted_counts) // 4]
    q3 = sorted_counts[3 * len(sorted_counts) // 4]

    print(f"\n{name} Statistics:")
    print(f"Total {name.lower()}: {len(data)}")
    print(f"Total occurrences: {total}")
    print(f"Mean frequency: {mean:.2f}")
    print(f"Median frequency: {median:.2f}")
    print(f"Standard deviation: {stdev:.2f}")
    print(f"Q1 (25th percentile): {q1}")
    print(f"Q3 (75th percentile): {q3}")
    print(f"IQR (Q3-Q1): {q3-q1}")
    print(f"Min frequency: {min(counts)}")
    print(f"Max frequency: {max(counts)}")

def load_cached_data(directory_path: str) -> Optional[ProcessedData]:
    """Load cached data from JSON file if it exists."""
    json_path = os.path.join(directory_path, 'ngram_counts.json')
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return ProcessedData.from_json(data)
        except Exception as e:
            print(f"Error loading cached data: {str(e)}")
    return None

def process_text_files(directory_path: str, config: Config) -> ProcessedData:
    """Process all text files in the given directory."""
    if not os.path.exists(directory_path):
        raise ValueError(f"Directory {directory_path} does not exist")

    # Clean up any existing files
    allwords_path = os.path.join(directory_path, 'allwords.txt')
    json_path = os.path.join(directory_path, 'ngram_counts.json')
    
    try:
        if os.path.exists(allwords_path):
            os.remove(allwords_path)
        if os.path.exists(json_path):
            os.remove(json_path)
    except Exception as e:
        print(f"Warning: Error cleaning up existing files: {str(e)}")

    # Load dictionary
    Concepts.ALL_WORDS_LIST = Concepts.load(Concepts.ALL_WORDS_LIST_FILENAME)
    dictionary = set(word.lower() for word in Concepts.ALL_WORDS_LIST)

    # Initialize counters
    bigram_counts = defaultdict(int)
    trigram_counts = defaultdict(int)
    word_counts = defaultdict(int)
    apostrophe_words = defaultdict(int)  # Track words with leading apostrophes
    invalid_apostrophe_words = defaultdict(int)  # Track words with mismatched counts

    # Word pattern for matching - now includes optional leading apostrophe
    word_pattern = re.compile(r'\'?\w+((-|\')?\w+)*')

    # Process each text file in the directory
    for filename in os.listdir(directory_path):
        if filename.endswith('.txt'):
            file_path = os.path.join(directory_path, filename)
            try:
                # Get excluded sections and patterns for this file
                file_excluded_sections = config.get_sections_for_file(filename)
                file_patterns = config.get_patterns_for_file(filename)
                
                with open(file_path, 'r', encoding='utf-8') as file:
                    # Process text paragraph by paragraph
                    paragraphs = []
                    current_paragraph = []
                    line_number = 0
                    
                    for line in file:
                        line_number += 1
                        line = line.strip()
                        
                        # Skip if this line is part of an excluded section
                        if any(start <= line_number <= end for start, end in file_excluded_sections):
                            continue
                            
                        # Skip if line matches any excluded pattern
                        if any(pattern in line for pattern in file_patterns):
                            continue
                            
                        if not line:  # Empty line indicates paragraph break
                            if current_paragraph:
                                paragraphs.append(current_paragraph)
                                current_paragraph = []
                            continue
                            
                        # Split line into sentences using NLTK's sentence tokenizer
                        sentences = sent_tokenize(line)
                        for sentence in sentences:
                            sentence = sentence.strip()
                            if not sentence:
                                continue
                                
                            # Find all words in the sentence
                            words = []
                            for match in word_pattern.finditer(sentence):
                                word = match.group().lower()
                                if not word:  # Skip empty strings
                                    continue
                                if is_valid_word(word):
                                    # Process possessives before adding to word list
                                    if config.remove_possessives:
                                        word = process_possessives(word)
                                    
                                    # Check for special cases
                                    if word in config.special_cases:
                                        word = config.special_cases[word]
                                        word_counts[word] += 1
                                        words.append(word)
                                    # If word starts with apostrophe, track both forms temporarily
                                    elif word.startswith("'"):
                                        word_without_apostrophe = word[1:]
                                        word_counts[word] += 1
                                        word_counts[word_without_apostrophe] += 1
                                        apostrophe_words[word] += 1
                                        words.append(word_without_apostrophe)  # Use form without apostrophe for n-grams
                                    else:
                                        word_counts[word] += 1
                                        words.append(word)
                            
                            if words:
                                current_paragraph.append(words)
                    
                    # Don't forget the last paragraph
                    if current_paragraph:
                        paragraphs.append(current_paragraph)
                    
                    # Generate n-grams within each sentence of each paragraph
                    for paragraph in paragraphs:
                        for sentence in paragraph:
                            # Skip empty sentences
                            if not sentence:
                                continue
                            # Generate bigrams
                            for i in range(len(sentence) - 1):
                                if sentence[i] and sentence[i + 1]:  # Ensure both words are non-empty
                                    bigram = (sentence[i], sentence[i + 1])
                                    bigram_counts[bigram] += 1
                            
                            # Generate trigrams
                            for i in range(len(sentence) - 2):
                                if sentence[i] and sentence[i + 1] and sentence[i + 2]:  # Ensure all words are non-empty
                                    trigram = (sentence[i], sentence[i + 1], sentence[i + 2])
                                    trigram_counts[trigram] += 1
                        
            except Exception as e:
                print(f"Error processing {filename}: {str(e)}")

    # Identify valid and invalid prepended-apostrophe words
    valid_apostrophe_words = []
    invalid_apostrophe_words = []
    apostrophe_map = {}  # Map non-apostrophe forms to apostrophe forms
    for word, count in apostrophe_words.items():
        if not word:  # Skip empty strings
            continue
        word_without_apostrophe = word[1:]
        if word_counts[word] == word_counts[word_without_apostrophe]:
            valid_apostrophe_words.append((word, count))
            # Remove the non-apostrophe form from word counts
            del word_counts[word_without_apostrophe]
            # Store mapping for n-gram updates
            apostrophe_map[word_without_apostrophe] = word
        else:
            invalid_apostrophe_words.append((word, word_counts[word], word_without_apostrophe, word_counts[word_without_apostrophe]))

    # Update n-grams to use apostrophe forms where valid
    updated_bigram_counts = defaultdict(int)
    for bigram, count in bigram_counts.items():
        # Skip if any word in the bigram is empty
        if not all(bigram):
            continue
        # Check each word in the bigram
        updated_bigram = tuple(apostrophe_map.get(word, word) for word in bigram)
        updated_bigram_counts[updated_bigram] += count

    updated_trigram_counts = defaultdict(int)
    for trigram, count in trigram_counts.items():
        # Skip if any word in the trigram is empty
        if not all(trigram):
            continue
        # Check each word in the trigram
        updated_trigram = tuple(apostrophe_map.get(word, word) for word in trigram)
        updated_trigram_counts[updated_trigram] += count

    # Create sorted lists
    sorted_bigrams = sorted(updated_bigram_counts.items(), key=lambda x: (-x[1], x[0]))
    sorted_trigrams = sorted(updated_trigram_counts.items(), key=lambda x: (-x[1], x[0]))
    sorted_words = sorted(word_counts.items(), key=lambda x: (-x[1], x[0]))
    
    # Create unknown words list from final word counts
    unknown_word_counts = {word: count for word, count in word_counts.items() if word and word not in dictionary}
    sorted_unknown_words = sorted(unknown_word_counts.items(), key=lambda x: (-x[1], x[0]))

    # Convert n-grams to strings for JSON serialization
    json_data: Dict[str, List[Dict[str, Any]]] = {
        'words': [{'word': word, 'count': count} for word, count in sorted_words],
        'bigrams': [{'ngram': ' '.join(bigram), 'count': count} for bigram, count in sorted_bigrams],
        'trigrams': [{'ngram': ' '.join(trigram), 'count': count} for trigram, count in sorted_trigrams],
        'unknown_words': [{'word': word, 'count': count} for word, count in sorted_unknown_words],
        'valid_apostrophe_words': [{'word': word, 'count': count} for word, count in sorted(valid_apostrophe_words, key=lambda x: (-x[1], x[0]))],
        'invalid_apostrophe_words': [{'word': word, 'apostrophe_count': apostrophe_count, 
                                    'without_apostrophe': without_apostrophe, 
                                    'without_apostrophe_count': without_apostrophe_count} 
                                   for word, apostrophe_count, without_apostrophe, without_apostrophe_count in sorted(invalid_apostrophe_words, key=lambda x: (-x[1], x[0]))]
    }

    # Save to JSON file
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_data, f)

    return ProcessedData(
        bigrams=sorted_bigrams,
        trigrams=sorted_trigrams,
        words=sorted_words,
        unknown_words=sorted_unknown_words,
        valid_apostrophe_words=sorted(valid_apostrophe_words, key=lambda x: (-x[1], x[0])),
        invalid_apostrophe_words=sorted(invalid_apostrophe_words, key=lambda x: (-x[1], x[0]))
    )

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Process text files to gather n-grams and word counts.')
    parser.add_argument('directory', help='Path to directory containing text files')
    parser.add_argument('--overwrite', action='store_true', help='Force reprocessing of files even if cached data exists')
    parser.add_argument('--unknown-words-dir', help='Directory to write alphabetized list of unknown words')
    parser.add_argument('--config', help='Path to configuration file (default: text_processor_config.json in script directory)')
    args = parser.parse_args()

    # Download required NLTK data
    download_nltk_data()

    try:
        # Load configuration
        config = load_config(args.config)
        if config.is_default:
            return  # Exit if config was just created from defaults
        print("Using config file: ", config.path)

        # Try to load cached data first if not overwriting
        if not args.overwrite:
            cached_data = load_cached_data(args.directory)
            if cached_data:
                print("Using cached data. Use --overwrite to force reprocessing.")
            else:
                cached_data = process_text_files(args.directory, config)
        else:
            cached_data = process_text_files(args.directory, config)
        
        # Print detailed statistics
        calculate_statistics(cached_data.words, "Word")
        calculate_statistics(cached_data.bigrams, "Bigram")
        calculate_statistics(cached_data.trigrams, "Trigram")
        
        # Print top 10 results
        print("\nTop 10 Words:")
        for word, count in cached_data.words[:10]:
            print(f"{word}: {count}")
            
        print("\nTop 10 Bigrams:")
        for bigram, count in cached_data.bigrams[:10]:
            print(f"{' '.join(bigram)}: {count}")
            
        print("\nTop 10 Trigrams:")
        for trigram, count in cached_data.trigrams[:10]:
            print(f"{' '.join(trigram)}: {count}")

        # Print unknown words
        if cached_data.unknown_words:
            print("\nWords not in dictionary (sorted by frequency):")
            for word, count in cached_data.unknown_words:
                print(f"{word}: {count}")

        # Print valid apostrophe words sorted by count
        if cached_data.valid_apostrophe_words:
            print("\nValid prepended-apostrophe words (matching counts):")
            for word, count in cached_data.valid_apostrophe_words:
                print(f"{word}: {count} (matches {word[1:]})")

        # Print invalid apostrophe words sorted by count
        if cached_data.invalid_apostrophe_words:
            print("\nPotentially invalid prepended-apostrophe words (mismatched counts):")
            for word, apostrophe_count, without_apostrophe, without_apostrophe_count in cached_data.invalid_apostrophe_words:
                print(f"{word}: {apostrophe_count} (vs {without_apostrophe}: {without_apostrophe_count})")

        # Write unknown words to file if directory specified
        if args.unknown_words_dir and cached_data.unknown_words:
            if not os.path.exists(args.unknown_words_dir):
                raise Exception(f"Directory {args.unknown_words_dir} does not exist! Cannot write unknown words to file.")
            
            # Define the output file path
            output_file = os.path.join(args.unknown_words_dir, 'unknown_words.txt')
            
            # Get just the words, sorted alphabetically
            unknown_words_list = sorted(word for word, _ in cached_data.unknown_words)
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(unknown_words_list))
            print(f"\nWrote {len(unknown_words_list)} unknown words to {output_file}")
            
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    main() 