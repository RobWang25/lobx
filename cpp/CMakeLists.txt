# The C++ matching core, its tests, a workload replay tool and the Python module.
#
# Checked build, with memory and undefined-behaviour checks:
#   cmake -S cpp -B build/cpp-asan -G Ninja -DCMAKE_BUILD_TYPE=Debug -DLOBX_SANITIZE=ON
#   (add -DLOBX_WERROR=ON to fail on warnings, as CI does)
#   cmake --build build/cpp-asan
#   ctest --test-dir build/cpp-asan --output-on-failure
#
# Optimized build, for speed, including the benchmarks:
#   cmake -S cpp -B build/cpp-release -G Ninja -DCMAKE_BUILD_TYPE=Release
#   cmake --build build/cpp-release
#   ./build/cpp-release/lobx_bench
#
# The Python module isn't built here. pip builds it through pyproject.toml, which
# runs this file with SKBUILD set:
#   .venv/bin/python -m pip install --no-build-isolation -e .

cmake_minimum_required(VERSION 3.25)
project(lobx_cpp CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Writes compile_commands.json, which tells editors like VS Code the exact
# flags and include paths each file is compiled with.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

option(LOBX_SANITIZE "Build with AddressSanitizer and UndefinedBehaviorSanitizer" OFF)

# Set before fetching dependencies, so they get the same checks as our code.
if(LOBX_SANITIZE)
  add_compile_options(
    -g
    -fsanitize=address,undefined
    -fno-sanitize-recover=undefined  # Stop at the first problem instead of continuing
    -fno-omit-frame-pointer          # Gives readable stack traces
  )
  add_link_options(-fsanitize=address,undefined)
endif()

# Downloads each dependency at a fixed version when CMake first configures the
# build. SYSTEM hides warnings from their headers, so we only see warnings about
# our own code.
include(FetchContent)
FetchContent_Declare(
  unordered_dense
  GIT_REPOSITORY https://github.com/martinus/unordered_dense.git
  GIT_TAG v4.5.0
  GIT_SHALLOW TRUE
  SYSTEM
)
FetchContent_MakeAvailable(unordered_dense)

# The core is header-only, so this library has nothing to compile. Linking to it
# passes on its include path and its dependency.
add_library(lobx_core INTERFACE)
target_include_directories(lobx_core INTERFACE include)
target_link_libraries(lobx_core INTERFACE unordered_dense::unordered_dense)

set(LOBX_WARNINGS -Wall -Wextra -Wpedantic -Wconversion -Wshadow)

# CI turns this on, so a warning in our code fails the build there. It's off by
# default, so a newer compiler's new warning doesn't stop anyone building locally.
option(LOBX_WERROR "Treat warnings in lobx's own code as errors" OFF)
if(LOBX_WERROR)
  list(APPEND LOBX_WARNINGS -Werror)
endif()

# SKBUILD is set when pip builds the package. Then we only need the Python module.
if(SKBUILD)
  find_package(Python 3.14 REQUIRED COMPONENTS Interpreter Development.Module)
  find_package(nanobind CONFIG REQUIRED)

  # Builds lobx/_core.<platform>.so. NB_STATIC links nanobind's own support code
  # into the module instead of shipping it as a separate library.
  nanobind_add_module(_core NB_STATIC bindings/module.cpp)
  target_link_libraries(_core PRIVATE lobx_core)
  target_compile_options(_core PRIVATE ${LOBX_WARNINGS})
  install(TARGETS _core LIBRARY DESTINATION lobx)
  return()
endif()

FetchContent_Declare(
  Catch2
  GIT_REPOSITORY https://github.com/catchorg/Catch2.git
  GIT_TAG v3.7.1
  GIT_SHALLOW TRUE
  SYSTEM
)
FetchContent_MakeAvailable(Catch2)

add_executable(lobx_tests
  tests/test_order_book.cpp
  tests/test_matching.cpp
  tests/test_no_allocation.cpp
  tests/test_ladders.cpp
)
target_link_libraries(lobx_tests PRIVATE lobx_core Catch2::Catch2WithMain)
target_compile_options(lobx_tests PRIVATE ${LOBX_WARNINGS})

add_executable(lobx_replay tools/replay.cpp)
target_link_libraries(lobx_replay PRIVATE lobx_core)
target_compile_options(lobx_replay PRIVATE ${LOBX_WARNINGS})

enable_testing()
add_test(NAME lobx_tests COMMAND lobx_tests)

# Benchmarks only make sense in an optimized build without sanitizers.
if(NOT LOBX_SANITIZE)
  set(BENCHMARK_ENABLE_TESTING OFF CACHE BOOL "" FORCE)
  set(BENCHMARK_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
  set(BENCHMARK_INSTALL_DOCS OFF CACHE BOOL "" FORCE)
  FetchContent_Declare(
    benchmark
    GIT_REPOSITORY https://github.com/google/benchmark.git
    GIT_TAG v1.9.1
    GIT_SHALLOW TRUE
    SYSTEM
  )
  FetchContent_MakeAvailable(benchmark)

  add_executable(lobx_bench bench/bench_core.cpp)
  target_link_libraries(lobx_bench PRIVATE lobx_core benchmark::benchmark)
  target_compile_options(lobx_bench PRIVATE ${LOBX_WARNINGS})
  # Where the workload files are, baked in as a string constant.
  target_compile_definitions(lobx_bench PRIVATE
    LOBX_WORKLOAD_DIR="${CMAKE_CURRENT_SOURCE_DIR}/../bench/workloads")
endif()
