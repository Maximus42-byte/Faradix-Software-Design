cmake_minimum_required(VERSION 3.22)
project(faradix_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(MSVC)
  set(FARADIX_WARNING_FLAGS /W4 /permissive-)
else()
  set(FARADIX_WARNING_FLAGS -Wall -Wextra -Wpedantic)
endif()

add_library(faradix_core src/engine.cpp)
target_include_directories(faradix_core PUBLIC include)
target_compile_options(faradix_core PRIVATE ${FARADIX_WARNING_FLAGS})

add_library(faradix_simulated_device src/simulated_device.cpp)
target_include_directories(faradix_simulated_device PUBLIC include)
target_link_libraries(faradix_simulated_device PUBLIC faradix_core)
target_compile_options(faradix_simulated_device PRIVATE ${FARADIX_WARNING_FLAGS})

add_library(faradix_development_json src/development_json.cpp)
target_include_directories(faradix_development_json PUBLIC include)
target_link_libraries(faradix_development_json PUBLIC faradix_core)
target_compile_options(faradix_development_json PRIVATE ${FARADIX_WARNING_FLAGS})

add_library(faradix_snapshot_adapter src/snapshot_writer.cpp)
target_include_directories(faradix_snapshot_adapter PUBLIC include)
target_link_libraries(faradix_snapshot_adapter PUBLIC faradix_development_json)
target_compile_options(faradix_snapshot_adapter PRIVATE ${FARADIX_WARNING_FLAGS})

add_library(faradix_recording_adapter src/recording_writer.cpp)
target_include_directories(faradix_recording_adapter PUBLIC include)
target_link_libraries(faradix_recording_adapter PUBLIC faradix_development_json)
target_compile_options(faradix_recording_adapter PRIVATE ${FARADIX_WARNING_FLAGS})

add_executable(faradix_engine src/main.cpp)
target_link_libraries(faradix_engine PRIVATE faradix_core faradix_simulated_device faradix_snapshot_adapter faradix_recording_adapter)
target_compile_options(faradix_engine PRIVATE ${FARADIX_WARNING_FLAGS})

include(CTest)
if(BUILD_TESTING)
  add_executable(faradix_engine_tests tests/engine_tests.cpp)
  target_link_libraries(faradix_engine_tests PRIVATE faradix_core faradix_simulated_device faradix_recording_adapter faradix_snapshot_adapter)
  target_compile_options(faradix_engine_tests PRIVATE ${FARADIX_WARNING_FLAGS})
  add_test(NAME engine_foundation COMMAND faradix_engine_tests)
  add_test(NAME bounded_cli COMMAND faradix_engine --steps 3 --period-ms 0)
endif()
