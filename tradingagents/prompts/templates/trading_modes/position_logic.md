Current Position: {current_position}

Position Transition Logic:
- If Current Position: LONG
  - Signal: LONG -> Hold the existing long exposure while the thesis remains valid
  - Signal: NEUTRAL -> Close the long position and move to cash
  - Signal: SHORT -> Close the long position and open a short position

- If Current Position: SHORT
  - Signal: SHORT -> Hold the existing short exposure while the thesis remains valid
  - Signal: NEUTRAL -> Close the short position and move to cash
  - Signal: LONG -> Close the short position and open a long position

- If Current Position: NEUTRAL (no open position)
  - Signal: LONG -> Open a long position when the evidence and risk controls justify it
  - Signal: SHORT -> Open a short position when the evidence and risk controls justify it
  - Signal: NEUTRAL -> Stay in cash and wait for a justified setup
