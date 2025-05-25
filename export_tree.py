import os
import fnmatch # For simpler pattern matching if pathspec isn't used for some initial checks
from pathlib import Path
import chardet # For robust encoding detection
import pathspec # For .gitignore parsing

# --- Configuration ---
# Directories to explicitly always ignore (even if not in .gitignore, like .git itself)
ALWAYS_IGNORED_DIRS = {'.git', '.vscode', '__pycache__', 'node_modules', 'venv', '.idea', 'dist', 'build'}
# File extensions to *additionally* treat as binary (add more as needed)
# .gitignore should handle most, but this is a fallback.
BINARY_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.ico',
    '.pdf',
    '.zip', '.tar', '.gz', '.rar', '.7z',
    '.exe', '.dll', '.so', '.o', '.a', '.lib',
    '.mp3', '.wav', '.ogg', '.mp4', '.avi', '.mov', '.mkv',
    '.sqlite', '.db', '.dat',
    '.pyc', '.pyo',
    '.class', '.jar',
    '.woff', '.woff2', '.ttf', '.otf',
    '.DS_Store'
}
# Specific files to explicitly always ignore
ALWAYS_IGNORED_FILES = {'package-lock.json', 'yarn.lock'} # Example

# Maximum file size to process (in bytes) to avoid very large files
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

# Output file name
OUTPUT_FILE = "project_snapshot_with_gitignore.txt"

def is_binary_string_heuristic(bytes_content, threshold=0.3):
    """
    Heuristic to check if a byte string likely contains binary data.
    Checks for a significant number of non-printable ASCII characters
    or null bytes.
    """
    if not bytes_content:
        return False
    # Check for null bytes, a strong indicator of binary files
    if b'\x00' in bytes_content:
        return True

    # Check for a high proportion of non-text characters
    # Common text characters (ASCII range, plus tab, LF, CR, FF, ESC)
    textchars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x7f)))
    non_text_char_count = sum(1 for byte in bytes_content if byte not in textchars)

    if len(bytes_content) == 0: # Should not happen if not bytes_content is checked
        return False
    # If more than `threshold`% are non-text characters, consider it binary
    return (non_text_char_count / len(bytes_content)) > threshold

def get_gitignore_rules(directory):
    """
    Loads .gitignore rules from a specific directory.
    Returns a PathSpec object.
    """
    gitignore_file = Path(directory) / ".gitignore"
    rules = []
    if gitignore_file.is_file():
        try:
            with open(gitignore_file, 'r', encoding='utf-8', errors='ignore') as f:
                rules.extend(f.read().splitlines())
        except Exception as e:
            print(f"Warning: Could not read .gitignore in {directory}: {e}")
    return pathspec.PathSpec.from_lines('gitwildmatch', rules) if rules else None


def get_combined_gitignore_rules(start_dir, current_path):
    """
    Traverses up from current_path to start_dir, accumulating .gitignore rules.
    Lower .gitignore files (closer to the file) take precedence for negations,
    but patterns are generally additive. Pathspec handles most of this complexity.
    """
    all_rules = []
    path = Path(current_path)
    if path.is_file():
        path = path.parent

    # Iterate from current directory up to the root of the processing (start_dir)
    while path.resolve() != Path(start_dir).parent.resolve() and path.exists() : # path >= Path(start_dir):
        gitignore_file = path / ".gitignore"
        if gitignore_file.is_file():
            try:
                with open(gitignore_file, 'r', encoding='utf-8', errors='ignore') as f:
                    # Pathspec needs paths relative to the .gitignore file's location
                    # However, for matching, we provide paths relative to the root.
                    # The library handles this by taking the .gitignore file's location into account.
                    # We just collect all lines.
                    lines = [line for line in f.read().splitlines() if line.strip() and not line.strip().startswith('#')]
                    all_rules.extend(lines) # Add rules from this .gitignore
            except Exception as e:
                print(f"Warning: Could not read or process .gitignore in {path}: {e}")
        if path == Path(start_dir): # Stop once we processed .gitignore in start_dir
            break
        if path.parent == path: # Reached root of filesystem
            break
        path = path.parent

    # PathSpec.from_lines expects patterns. It will handle the precedence and combination.
    return pathspec.PathSpec.from_lines('gitwildmatch', all_rules) if all_rules else None

def get_project_structure(root_dir_path, all_collected_files):
    """
    Generates a string representation of the project's directory structure
    based on the files that will actually be included.
    """
    structure_str = "Project Structure (Files to be Included):\n"
    structure_str += f"Root: {root_dir_path.name}/\n"

    # Create a directory tree structure
    tree = {}
    for rel_path_str in all_collected_files:
        parts = Path(rel_path_str).parts
        current_level = tree
        for part in parts:
            if part not in current_level:
                current_level[part] = {}
            current_level = current_level[part]

    def generate_tree_lines(current_level, indent_level=0):
        lines = []
        prefix = '    ' * indent_level
        items = sorted(current_level.keys())
        for i, name in enumerate(items):
            connector = '└── ' if i == len(items) - 1 else '├── '
            is_dir = bool(current_level[name]) # True if it's a dict (directory), False otherwise
            lines.append(f"{prefix}{connector}{name}{'/' if is_dir else ''}")
            if is_dir:
                lines.extend(generate_tree_lines(current_level[name], indent_level + 1))
        return lines

    structure_str += "\n".join(generate_tree_lines(tree, 0)) # Start indent from root
    structure_str += "\n\n" + "="*80 + "\n\n"
    return structure_str


def process_project(root_dir, output_file_path):
    """
    Processes the project directory respecting .gitignore and writes content.
    """
    root_dir_path = Path(root_dir).resolve()
    collected_files_content = [] # Store (relative_path, content_type, content_or_message)

    # --- First Pass: Collect all files respecting .gitignore and other rules ---
    print("Phase 1: Scanning project and applying .gitignore rules...")
    files_to_process = [] # List of (absolute_path, relative_path)

    # Load root .gitignore if present (for initial directory pruning)
    # More specific .gitignores will be checked during traversal
    root_spec = get_gitignore_rules(root_dir_path)

    for current_root_str, dirs, files in os.walk(root_dir_path, topdown=True):
        current_root_path = Path(current_root_str)
        relative_current_root = current_root_path.relative_to(root_dir_path)

        # Combine rules from all .gitignores from root_dir_path up to current_root_path's parent
        # This ensures correct handling of nested .gitignore files
        # For matching files/dirs *within* current_root_path, we use spec from current_root_path itself (and parents)
        effective_spec = get_combined_gitignore_rules(root_dir_path, current_root_path)

        # Filter directories
        original_dirs = list(dirs) # copy before modification
        dirs[:] = [d for d in original_dirs if d not in ALWAYS_IGNORED_DIRS]
        if effective_spec:
            # Pathspec needs paths relative to the location of the .gitignore files it parsed from,
            # or, more simply, give it paths relative to the 'root' you are matching against.
            # Here, we give it paths relative to root_dir_path for directories.
            # pathspec expects paths with '/' as separator
            dirs[:] = [d for d in dirs if not effective_spec.match_file(str(relative_current_root / d).replace(os.sep, '/'))]
        dirs.sort() # For consistent order

        # Filter files
        files.sort() # For consistent order
        for filename in files:
            file_path = current_root_path / filename
            relative_path = file_path.relative_to(root_dir_path)
            relative_path_str = str(relative_path).replace(os.sep, '/') # Use POSIX paths for matching

            if filename in ALWAYS_IGNORED_FILES or any(fnmatch.fnmatch(filename, p) for p in ALWAYS_IGNORED_FILES): # for potential patterns in ALWAYS_IGNORED_FILES
                 print(f"Skipping (always ignored file): {relative_path_str}")
                 continue

            if effective_spec and effective_spec.match_file(relative_path_str):
                print(f"Skipping (ignored by .gitignore): {relative_path_str}")
                continue

            files_to_process.append((file_path, relative_path))


    # --- Second Pass: Process collected files and write to output ---
    print(f"\nPhase 2: Processing {len(files_to_process)} identified files...")
    with open(output_file_path, 'w', encoding='utf-8', errors='replace') as outfile:
        # 1. Write Project Structure based on files that WILL be included
        outfile.write(get_project_structure(root_dir_path, [str(rp) for _, rp in files_to_process]))
        outfile.write("File Contents:\n")
        outfile.write("="*80 + "\n\n")

        # 2. Include contents of .gitignore files first
        gitignore_files_processed = set()
        for current_root_str, _, _ in os.walk(root_dir_path, topdown=True): # Fresh walk to find all .gitignores
            current_root_path = Path(current_root_str)
            if any(part in ALWAYS_IGNORED_DIRS for part in current_root_path.relative_to(root_dir_path).parts):
                continue # Skip .gitignores in always ignored dirs like .git/

            gitignore_path = current_root_path / ".gitignore"
            if gitignore_path.is_file() and gitignore_path not in gitignore_files_processed:
                relative_gitignore_path = gitignore_path.relative_to(root_dir_path)
                outfile.write(f"--- File: {str(relative_gitignore_path).replace(os.sep, '/')} (.gitignore) ---\n")
                try:
                    with open(gitignore_path, 'r', encoding='utf-8', errors='ignore') as gf:
                        lines = gf.read().splitlines()
                        if not lines:
                            outfile.write("[Empty .gitignore file]\n")
                        for i, line in enumerate(lines):
                            outfile.write(f"{i+1:04d}\t{line}\n")
                        outfile.write("\n\n")
                    gitignore_files_processed.add(gitignore_path)
                except Exception as e:
                    outfile.write(f"[Error reading .gitignore file: {e}]\n\n\n")
                    print(f"Error reading .gitignore {relative_gitignore_path}: {e}")


        # 3. Process and write content of other files
        for file_path, relative_path in files_to_process:
            relative_path_str = str(relative_path).replace(os.sep, '/') # For display
            outfile.write(f"--- File: {relative_path_str} ---\n")
            _, extension = os.path.splitext(file_path.name.lower())

            # Check for binary extensions (additional safety)
            if extension in BINARY_EXTENSIONS:
                outfile.write("[Binary file (by extension) - content not included]\n\n\n")
                print(f"Info: File '{relative_path_str}' identified as binary by extension.")
                continue

            # Check file size
            try:
                file_size = file_path.stat().st_size
                if file_size > MAX_FILE_SIZE_BYTES:
                    outfile.write(f"[File too large ({file_size / (1024*1024):.2f} MB) - content not included]\n\n\n")
                    print(f"Skipping (too large): {relative_path_str}")
                    continue
                if file_size == 0:
                    outfile.write("[Empty file]\n\n\n")
                    print(f"Info: File '{relative_path_str}' is empty.")
                    continue
            except OSError as e:
                outfile.write(f"[Error accessing file size: {e} - content not included]\n\n\n")
                print(f"Error accessing file size for {relative_path_str}: {e}")
                continue

            # Read and process the file content
            try:
                with open(file_path, 'rb') as f: # Read as binary first for detection
                    raw_content = f.read()

                # Try to detect encoding
                detected = chardet.detect(raw_content)
                encoding = detected['encoding'] if detected['encoding'] and detected['confidence'] > 0.5 else 'utf-8'

                # Heuristic check for binary content
                if is_binary_string_heuristic(raw_content):
                    # Double check if it's an extension we might sometimes want (e.g. .svg, .json if large and weird)
                    # For now, trust the heuristic if it triggers
                    outfile.write("[Likely binary file (content heuristic) - content not included]\n\n\n")
                    print(f"Skipping (likely binary by heuristic): {relative_path_str} (Detected encoding: {encoding} with confidence {detected['confidence']})")
                    continue

                try:
                    content = raw_content.decode(encoding, errors='replace')
                except UnicodeDecodeError:
                    # Fallback for stubborn cases
                    content = raw_content.decode('latin-1', errors='replace')
                    print(f"Warning: File {relative_path_str} decoded as 'latin-1' after '{encoding}' failed.")


                lines = content.splitlines()
                if not lines and file_size > 0 : # File has size but no lines after split (e.g. binary that passed heuristic or just no newlines)
                    outfile.write("[File has content but no standard line breaks, or is binary and passed heuristics - partial/raw dump attempt below if small]\n")
                    # For very small such files, a snippet might be okay, otherwise skip.
                    if len(raw_content) < 200: # Small enough to potentially be a snippet
                         outfile.write(f"Raw (first 200 bytes, possibly problematic): {raw_content[:200].decode('latin-1', errors='replace')}\n")
                    else:
                         outfile.write("[Content not displayed due to unusual format and size]\n")
                elif not lines and file_size == 0:
                    # Already handled by file_size == 0 check, but as a safeguard:
                    outfile.write("[Empty file]\n")
                else:
                    for i, line in enumerate(lines):
                        outfile.write(f"{i+1:04d}\t{line}\n")
                outfile.write("\n\n")

            except FileNotFoundError:
                # Should not happen due to pre-collection, but good to have
                outfile.write("[File not found during processing - might be a broken symlink or removed]\n\n\n")
                print(f"File not found: {file_path}")
            except IOError as e:
                outfile.write(f"[IOError reading file: {e} - content not included]\n\n\n")
                print(f"IOError reading {relative_path_str}: {e}")
            except Exception as e:
                outfile.write(f"[Unexpected error processing file: {e} - content not included]\n\n\n")
                print(f"Unexpected error with {relative_path_str}: {e}")

        print(f"\nProject content successfully written to {output_file_path}")
        print(f"Please review '{output_file_path}' for any sensitive information before sharing.")
        print("Consider zipping the output file if it's very large.")

if __name__ == "__main__":
    project_directory = os.getcwd() # Assumes the script is in the root of the project
    # project_directory = "/path/to/your/repo" # Or set a specific path here for testing

    output_file = Path(project_directory) / OUTPUT_FILE

    print(f"Starting to process project in: {project_directory}")
    print(f"Output will be saved to: {output_file}")
    print(f"Always ignored Dirs: {ALWAYS_IGNORED_DIRS}")
    print(f"Always ignored Files: {ALWAYS_IGNORED_FILES}")
    print(f"Additional binary extensions: {BINARY_EXTENSIONS}")
    print("---")

    try:
        process_project(project_directory, output_file)
    except ImportError as e:
        if 'pathspec' in str(e):
            print("ERROR: The 'pathspec' library is not installed. Please install it:")
            print("  pip install pathspec")
        elif 'chardet' in str(e):
            print("ERROR: The 'chardet' library is not installed. Please install it:")
            print("  pip install chardet")
        else:
            print(f"ERROR: An import error occurred: {e}")
        print("Script cannot continue without this dependency.")
    except Exception as e:
        print(f"An unexpected critical error occurred: {e}")
