# Small programs that check the C++ toolchain and demonstrate concepts used by
# the port. Build and run them with:
#
#   cmake -S cpp/examples -B build/examples -G Ninja
#   cmake --build build/examples
#   ./build/examples/references
#   ./build/examples/dangling

cmake_minimum_required(VERSION 3.20)
project(lobx_examples CXX)

# Use standard C++20, without compiler-specific language extensions.
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# -Wall -Wextra -Wpedantic: warn about suspicious code.
# -fsanitize: add runtime checks for memory errors and undefined behaviour.
add_compile_options(-Wall -Wextra -Wpedantic -g -fsanitize=address,undefined -fno-omit-frame-pointer)
add_link_options(-fsanitize=address,undefined)

add_executable(references references.cpp)
add_executable(dangling dangling.cpp)
