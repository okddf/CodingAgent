# Codebase Documentation

## `compression.cpp`

**Summary**: The file implements a compression and decompression utility in C++, allowing the conversion of text files into a compressed format using specified replacements and vice versa. It provides functions to replace words in a text file with designated symbols for compression and to restore those symbols back to original words during decompression.

## `compression`
**Description**: Class purpose

**Attributes**:
| Name | Type | Description |
|------|------|-------------|


**Methods**:


**Example Usage**:
```C++
usage example code
```

### `compress(read_from, write_to, replacement) -> void`
**Description**: Compresses text from a source file, replacing specified words according to a map.

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `read_from` | `string` | `None` | Path to the input file from which text will be read. |
| `write_to` | `string` | `None` | Path to the output file where compressed text will be written. |
| `replacement` | `map<string, string>` | `None` | Map containing pairs of words to be replaced and their replacements. |

**Returns**:
| Type | Description |
|------|-------------|
| `void` | This function does not return a value. |

**Example Usage**:
```C++
compression::compress("input.txt", "output.txt", {{"word1", "replacement1"}, {"word2", "replacement2"}});
```

### `decompress(read_from, write_to) -> void`
**Description**: Decompresses data from a specified input file to a specified output file by replacing words using a predefined mapping.

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `read_from` | `string` | `None` | The name of the input file to read data from. |
| `write_to` | `string` | `None` | The name of the output file to write decompressed data to. |

**Returns**:
| Type | Description |
|------|-------------|
| `void` | This function does not return a value. |

**Example Usage**:
```C++
compression::decompress("input.txt", "output.txt");
```

---

## `main.cpp`

**Summary**: The file provides a main program that reads word frequency data from a specified text file, retrieves and displays the five most frequent words, and then compresses the original text file using this frequency information before decompressing it back to a new file.

### `main() -> int`
**Description**: Entry point of the program that reads a file, gets word frequency, and performs compression and decompression.

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|


**Returns**:
| Type | Description |
|------|-------------|
| `int` | Returns 0 on successful execution. |

**Example Usage**:
```C++
int main() { read_from_file file; file.read_word_freq("..\test.txt"); file.get_word_freq(); map<string, string> top_five = file.get_top_five(); for(auto i : top_five) { cout << i.first << " " << i.second << endl; } compression comp; comp.compress("..\test.txt", "..\out.txt", top_five); comp.decompress("..\out.txt", "..\dectest.txt"); }
```

---

## `read_from_file.cpp`

**Summary**: The purpose of the file is to read a list of words from a specified text file, count the frequency of each word with a length of three or more characters, and provide functions to output the word frequencies and retrieve the top five most frequent words, each labeled with a unique identifier. It also handles cases where the file cannot be opened or there are fewer than five qualifying words in the text.

## `read_from_file`
**Description**: This class handles reading data from a file.

**Attributes**:
| Name | Type | Description |
|------|------|-------------|


**Methods**:


**Example Usage**:
```C++
read_from_file r; r.some_method();
```

### `read_word_freq(filename) -> void`
**Description**: Reads words from a file and updates their frequency count.

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `filename` | `std::string` | `None` | Name of the file to read. |

**Returns**:
| Type | Description |
|------|-------------|
| `void` | No return value. |

**Example Usage**:
```C++
read_from_file obj; obj.read_word_freq("example.txt");
```

### `get_word_freq() -> void`
**Description**: Prints the word frequency from the word_freq map.

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|


**Returns**:
| Type | Description |
|------|-------------|
| `void` | No return value. |

**Example Usage**:
```C++
read_from_file obj; obj.get_word_freq();
```

### `get_top_five() -> map<string, string>`
**Description**: Retrieves the top five words by frequency from the word_freq map.

**Parameters**:
| Name | Type | Default | Description |
|------|------|---------|-------------|


**Returns**:
| Type | Description |
|------|-------------|
| `map<string, string>` | A map containing the top five words and their corresponding exclamatory numbers. |

**Example Usage**:
```C++
map<string, string> top_words = read_from_file_instance.get_top_five();
```

---

