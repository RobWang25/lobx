execute_process(
  COMMAND "${REPLAY}" "${WORKLOAD}"
  RESULT_VARIABLE result
  ERROR_VARIABLE diagnostic
)
string(STRIP "${diagnostic}" diagnostic)
if(NOT result STREQUAL "1" OR
   NOT diagnostic STREQUAL "error: ${WORKLOAD}:2: invalid workload operation")
  message(FATAL_ERROR "Expected invalid workload on line 2, got result ${result}\n${diagnostic}")
endif()
