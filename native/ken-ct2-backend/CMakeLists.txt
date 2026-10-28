cmake_minimum_required(VERSION 3.31)
project(ken_ct2_backend LANGUAGES CXX)
if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux" OR NOT CMAKE_SYSTEM_PROCESSOR STREQUAL "x86_64")
  message(FATAL_ERROR "The registered CT2 CPU module requires Linux x86_64")
endif()
if(NOT DEFINED KEN_CT2_SDK OR NOT DEFINED KEN_CT2_CORE_LIBRARY)
  message(FATAL_ERROR "Explicit authenticated CT2 SDK and core library required")
endif()
add_library(ken_ct2_backend SHARED src/translation.cpp)
target_compile_features(ken_ct2_backend PRIVATE cxx_std_17)
target_include_directories(ken_ct2_backend PRIVATE include "${KEN_CT2_SDK}/include")
target_compile_options(ken_ct2_backend PRIVATE -Wall -Wextra -Werror)
target_link_libraries(ken_ct2_backend PRIVATE "${KEN_CT2_CORE_LIBRARY}")
target_link_options(ken_ct2_backend PRIVATE -Wl,--disable-new-dtags "-Wl,-rpath-link,${KEN_CT2_SDK}/lib")
set_target_properties(ken_ct2_backend PROPERTIES
  CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN YES
  BUILD_RPATH "$ORIGIN" BUILD_RPATH_USE_ORIGIN YES
  INSTALL_RPATH "$ORIGIN" BUILD_WITH_INSTALL_RPATH YES)
