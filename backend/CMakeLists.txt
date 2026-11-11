cmake_minimum_required(VERSION 3.15...3.30)
project(${SKBUILD_PROJECT_NAME} LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
find_package(pybind11 CONFIG REQUIRED)

# The C++ router must reproduce Python's floating-point sums exactly (parity tests), so no -ffast-math.
pybind11_add_module(_fastroute src/fastroute.cpp)
install(TARGETS _fastroute DESTINATION platetrail)
