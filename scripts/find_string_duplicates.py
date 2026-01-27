#!/usr/bin/env python3
"""
Script to find potential duplicates in a text file.
Compares strings ignoring case, whitespace, and structural elements.
Uses semantic similarity for near-duplicates.
"""

import os
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher, unified_diff

# Ensure we are running from the project root for imports and relative paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

try:
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    HAS_SEMANTIC = True
except ImportError:
    HAS_SEMANTIC = False
    print("Warning: sentence-transformers and scikit-learn not available. Using text similarity only.")


def normalize_text(text):
    """Normalize text for comparison: lowercase, remove brackets, normalize whitespace."""
    # Remove [[...]] patterns (variations)
    text = re.sub(r'\[\[.*?\]\]', '', text)
    # Remove parentheses and their contents
    text = re.sub(r'\([^)]*\)', '', text)
    # Remove special characters except spaces
    text = re.sub(r'[^\w\s]', ' ', text)
    # Normalize whitespace
    text = ' '.join(text.lower().split())
    return text.strip()


def find_exact_duplicates(lines):
    """Find exact duplicates after normalization."""
    normalized_map = defaultdict(list)
    for idx, line in enumerate(lines, 1):
        normalized = normalize_text(line)
        if normalized:  # Skip empty lines after normalization
            normalized_map[normalized].append((idx, line))
    
    duplicates = []
    for normalized, occurrences in normalized_map.items():
        if len(occurrences) > 1:
            duplicates.append((normalized, occurrences))
    
    return duplicates


def find_similar_duplicates(lines, threshold=0.85):
    """Find similar duplicates using text similarity."""
    normalized_lines = [(idx, normalize_text(line), line) 
                        for idx, line in enumerate(lines, 1) 
                        if normalize_text(line)]
    
    similar_pairs = []
    seen = set()
    
    for i, (idx1, norm1, orig1) in enumerate(normalized_lines):
        if norm1 in seen:
            continue
        matches = [(idx1, orig1, 1.0)]  # Store with similarity score
        
        for idx2, norm2, orig2 in normalized_lines[i+1:]:
            if norm2 in seen:
                continue
            
            # Calculate similarity
            similarity = SequenceMatcher(None, norm1, norm2).ratio()
            
            if similarity >= threshold:
                matches.append((idx2, orig2, similarity))
                seen.add(norm2)
        
        if len(matches) > 1:
            # Sort by similarity (descending), then by line number
            matches.sort(key=lambda x: (-x[2], x[0]))
            similar_pairs.append((norm1, matches))
            seen.add(norm1)
    
    # Sort groups by highest cross-line similarity (exclude the 1.0 self-match)
    similar_pairs.sort(key=lambda x: -max((m[2] for m in x[1][1:]), default=0))
    return similar_pairs


def find_semantic_duplicates(lines, threshold=0.85):
    """Find semantic duplicates using sentence transformers."""
    if not HAS_SEMANTIC:
        return []
    
    print("Loading semantic model...")
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    # Prepare texts
    texts = []
    text_map = []
    for idx, line in enumerate(lines, 1):
        normalized = normalize_text(line)
        if normalized and len(normalized) > 3:  # Skip very short lines
            texts.append(normalized)
            text_map.append((idx, line, normalized))
    
    if len(texts) < 2:
        return []
    
    print(f"Encoding {len(texts)} texts...")
    embeddings = model.encode(texts, show_progress_bar=True)
    
    print("Finding similar pairs...")
    similar_pairs = []
    seen = set()
    
    for i, (idx1, orig1, norm1) in enumerate(text_map):
        if i in seen:
            continue
        
        matches = [(idx1, orig1)]
        for j, (idx2, orig2, norm2) in enumerate(text_map[i+1:], i+1):
            if j in seen:
                continue
            
            similarity = cosine_similarity(
                embeddings[i:i+1], 
                embeddings[j:j+1]
            )[0][0]
            
            if similarity >= threshold:
                matches.append((idx2, orig2))
                seen.add(j)
        
        if len(matches) > 1:
            similar_pairs.append((norm1, matches))
            seen.add(i)
    
    return similar_pairs


def print_similar_duplicates(similar_dups, threshold, show_diffs=False):
    """Print similar duplicates with similarity scores and optionally differences."""
    if similar_dups:
        for normalized, occurrences in similar_dups:
            print(f"\nNormalized: '{normalized}'")
            base_idx, base_line, _ = occurrences[0]
            print(f"  Line {base_idx}: {base_line}")
            
            for idx, orig, sim_score in occurrences[1:]:
                # Check if lines are close together (likely accidental)
                proximity = " [NEARBY]" if abs(idx - base_idx) <= 5 else ""
                print(f"  Line {idx}: {orig} (similarity: {sim_score:.2%}){proximity}")
                
                # Show what's different for very similar lines (only if requested)
                if show_diffs and sim_score >= 0.90 and sim_score < 1.0:
                    base_norm = normalize_text(base_line)
                    orig_norm = normalize_text(orig)
                    if base_norm != orig_norm:
                        # Find key differences
                        diff = list(unified_diff(
                            base_norm.split(), 
                            orig_norm.split(), 
                            lineterm='', 
                            n=0
                        ))
                        if diff:
                            changes = ' '.join(diff[2:])  # Skip header lines
                            if len(changes) < 100:  # Only show if not too long
                                print(f"    Differences: {changes}")
    else:
        print("No similar duplicates found.\n")


def export_results(export_file, file_path, lines, exact_dups, similar_dups, semantic_dups, threshold, use_semantic):
    """Export duplicate analysis results to a file."""
    print(f"\nExporting results to {export_file}...")
    with open(export_file, 'w', encoding='utf-8') as f:
        f.write(f"Duplicate Analysis for: {file_path}\n")
        f.write(f"Total lines: {len(lines)}\n\n")
        
        f.write("=" * 80 + "\n")
        f.write("EXACT DUPLICATES\n")
        f.write("=" * 80 + "\n")
        for normalized, occurrences in exact_dups:
            f.write(f"\nNormalized: '{normalized}'\n")
            for idx, orig in occurrences:
                f.write(f"  Line {idx}: {orig}\n")
        
        f.write("\n" + "=" * 80 + "\n")
        f.write(f"SIMILAR DUPLICATES (threshold={threshold})\n")
        f.write("=" * 80 + "\n")
        for normalized, occurrences in similar_dups:
            f.write(f"\nNormalized: '{normalized}'\n")
            base_idx, base_line, _ = occurrences[0]
            f.write(f"  Line {base_idx}: {base_line}\n")
            for idx, orig, sim_score in occurrences[1:]:
                proximity = " [NEARBY]" if abs(idx - base_idx) <= 5 else ""
                f.write(f"  Line {idx}: {orig} (similarity: {sim_score:.2%}){proximity}\n")
        
        if use_semantic and semantic_dups:
            f.write("\n" + "=" * 80 + "\n")
            f.write(f"SEMANTIC DUPLICATES (threshold={threshold})\n")
            f.write("=" * 80 + "\n")
            for normalized, occurrences in semantic_dups:
                f.write(f"\nNormalized: '{normalized}'\n")
                for idx, orig in occurrences:
                    f.write(f"  Line {idx}: {orig}\n")
    
    print(f"Results exported to {export_file}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python find_duplicates.py <file_path> [--semantic] [--threshold=0.85] [--export=<file>] [--show-diffs]")
        sys.exit(1)
    
    file_path = sys.argv[1]
    use_semantic = '--semantic' in sys.argv
    show_diffs = '--show-diffs' in sys.argv
    threshold = 0.85
    export_file = None
    
    # Parse arguments
    for arg in sys.argv:
        if arg.startswith('--threshold='):
            threshold = float(arg.split('=')[1])
        elif arg.startswith('--export='):
            export_file = arg.split('=', 1)[1]
    
    print(f"Reading {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = [line.rstrip('\n\r') for line in f]
    
    print(f"Found {len(lines)} lines\n")
    
    # Find exact duplicates
    print("=" * 80)
    print("EXACT DUPLICATES (after normalization)")
    print("=" * 80)
    exact_dups = find_exact_duplicates(lines)
    if exact_dups:
        for normalized, occurrences in exact_dups:
            print(f"\nNormalized: '{normalized}'")
            for idx, orig in occurrences:
                print(f"  Line {idx}: {orig}")
    else:
        print("No exact duplicates found.\n")
    
    # Find similar duplicates
    print("\n" + "=" * 80)
    print(f"SIMILAR DUPLICATES (text similarity, threshold={threshold})")
    print("=" * 80)
    similar_dups = find_similar_duplicates(lines, threshold)
    print_similar_duplicates(similar_dups, threshold, show_diffs)
    
    # Find semantic duplicates if requested
    if use_semantic:
        print("\n" + "=" * 80)
        print(f"SEMANTIC DUPLICATES (sentence transformers, threshold={threshold})")
        print("=" * 80)
        semantic_dups = find_semantic_duplicates(lines, threshold)
        if semantic_dups:
            for normalized, occurrences in semantic_dups:
                print(f"\nNormalized: '{normalized}'")
                for idx, orig in occurrences:
                    print(f"  Line {idx}: {orig}")
        else:
            print("No semantic duplicates found.\n")
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Exact duplicates: {len(exact_dups)} groups")
    print(f"Similar duplicates: {len(similar_dups)} groups")
    if use_semantic:
        print(f"Semantic duplicates: {len(semantic_dups)} groups")
    
    # Export results if requested
    if export_file:
        export_results(export_file, file_path, lines, exact_dups, similar_dups, semantic_dups, threshold, use_semantic)


if __name__ == '__main__':
    main()
