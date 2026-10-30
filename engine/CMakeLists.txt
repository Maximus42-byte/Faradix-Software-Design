cmake_minimum_required(VERSION 3.22)
project(faradix_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(faradix_core src/engine.cpp)
target_include_directories(faradix_core PUBLIC include)
target_compile_options(faradix_core PRIVATE -Wall -Wextra -Wpedantic)

add_library(faradix_simulated_device src/simulated_device.cpp)
target_include_directories(faradix_simulated_device PUBLIC include)
target_link_libraries(faradix_simulated_device PUBLIC faradix_core)
target_compile_options(faradix_simulated_device PRIVATE -Wall -Wextra -Wpedantic)

add_library(faradix_snapshot_adapter src/snapshot_writer.cpp)
target_include_directories(faradix_snapshot_adapter PUBLIC include)
target_link_libraries(faradix_snapshot_adapter PUBLIC faradix_core)
target_compile_options(faradix_snapshot_adapter PRIVATE -Wall -Wextra -Wpedantic)

add_executable(faradix_engine src/main.cpp)
target_link_libraries(faradix_engine PRIVATE faradix_core faradix_simulated_device faradix_snapshot_adapter)
target_compile_options(faradix_engine PRIVATE -Wall -Wextra -Wpedantic)

include(CTest)
if(BUILD_TESTING)
  add_executable(faradix_engine_tests tests/engine_tests.cpp)
  target_link_libraries(faradix_engine_tests PRIVATE faradix_core faradix_simulated_device)
  target_compile_options(faradix_engine_tests PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME engine_foundation COMMAND faradix_engine_tests)
  add_test(NAME bounded_cli COMMAND faradix_engine --steps 3 --period-ms 0)
endif()
