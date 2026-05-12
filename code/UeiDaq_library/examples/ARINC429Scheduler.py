import UeiDaq

#   Python Implementation of a scheduling writer to write individual words to a 429-566 board
#   Uses customized versions of C++ read and write functions
#   Continuously schedules ARINC words to be sent on TX port 0, and receives on RX port 0 and 1
#   When reading the words back from the board, they are returned in a 2d array.
#   ex.     returnWords [word index][word data]
#   Where the word data is stored as
#                   [0] => Label
#                   [1] => Data
#                   [2] => Sdi
#                   [3] => Ssm
#                   [4] => Parity
#   Uses non-swig generated helper functions for the scheduling of words.
#
#   For further information on swig generated functions, visit the "UeiDaqPy.i" file.

numWords = 12

try:
    session = UeiDaq.CUeiSession()
    

    session.CreateARINCOutputPort("pdna://192.168.100.12/dev4/atx0",  # change this string to match your device out port
                                  UeiDaq.UeiARINCBitsPerSecond100000,
                                  UeiDaq.UeiARINCParityNone)

    outputPorts = session.GetNumberOfChannels()

    # Be sure to update the bits/sec, parity, and SDI to match the settings for your board
    session.CreateARINCInputPort("pdna://192.168.100.12/dev4/arx6",  # change this string to match device input ports
                                 UeiDaq.UeiARINCBitsPerSecond100000,
                                 UeiDaq.UeiARINCParityNone,
                                 False,
                                 0)
    inputPorts = session.GetNumberOfChannels()  - outputPorts  # read input ports so we know what arinc board we're dealing with.

    session.ConfigureTimingForMessagingIO(1, 0)  # configure session for IO messaging

    session.GetTiming().SetTimeout(10)  # set timing to low value to avoid blocking the program if no words are received

    readers = [UeiDaq.CUeiARINCReader(session.GetDataStream()) for i in
               range(inputPorts)]  # create list of readers to read from
    for ch in range(inputPorts):  # specify each reader as a channel specific reader
        readers[ch] = UeiDaq.CUeiARINCReader(session.GetDataStream(), session.GetChannel(outputPorts + ch).GetIndex())

    writers = [UeiDaq.CUeiARINCWriter(session.GetDataStream()) for i in
               range(outputPorts)]  # create list of writers to write to
    for ch in range(outputPorts):  # specify each writer as a channel specific writer
        writers[ch] = UeiDaq.CUeiARINCWriter(session.GetDataStream(), session.GetChannel(ch).GetIndex())

    for ch in range(outputPorts):  # Load up all the words we want to schedule for each port
        arincOutPort = session.GetARINCOutputPort(ch)
        for f in range(numWords):
            schedEntry = UeiDaq.tUeiARINCSchedulerEntry()

            # Every fourth entry is a master
            # Slave entries following the master entry are scheduled at the same time
            schedEntry.Master = (0 == (f % 4))

            # Master entry is periodic, and ignored for slave entries
            schedEntry.Periodic = 1

            # Master entry to output word 100ms after the trigger
            schedEntry.Delay = 100000

            # Set up each word to be written by this entry. Fills the data entries.
            newWord = UeiDaq.tUeiARINCWord()
            newWord.Label = f + ch
            newWord.Sdi = 1
            newWord.Ssm = 2
            newWord.Data = 2 * f
            newWord.Parity = 0
            schedEntry.Word = newWord
            # Word.Parity is defaulted, so is usually not set during word creation

            # This method below sends a scheduler entry to the given port. Uses a c++ helper function within
            # the swig wrapper to do pointer logic, as python restricts us from doing it here.
            arincOutPort.AddSchedulerEntry(schedEntry)

            #print(arincOutPort.GetSchedulerEntry(f).Label)

        # This method below enables/disables the ARINC scheduler for a port.
        arincOutPort.EnableScheduler(True)

   
    session.Start()  # Start the session for reading and writing.
    
    for i in range(100):  # Go through the schedule write read cycle 100 times.
        for ch in range(inputPorts):
            port = session.GetChannel(outputPorts + ch).GetIndex()

            try:
                returnWords = readers[ch].Read(numWords)  # Read the words from the board into an array to be printed
            except Exception as e:
                if e.args[0] == UeiDaq.UEIDAQ_TIMEOUT_ERROR:
                    print("ARINC input reading timed out!")
                    continue
                # Rethrow any error that is not a timeout error for the main exception handler to catch
                raise
            
            numWordsRead = len(returnWords)
            print("%d RX Port %d: Received %d words" % (i, port, numWordsRead))
            for v in range(numWordsRead):  # prints the word data received
                print ("RX port %d: Received word: Label=%d Data=%d Sdi=%d Ssm=%d Parity=%d" % (
                       port, returnWords[v].Label, returnWords[v].Data, returnWords[v].Sdi, returnWords[v].Ssm,
                       returnWords[v].Parity))

        if i == 50:  # Halfway through, we write all new words to the board.
            for ch in range(outputPorts):
                nwords = [UeiDaq.tUeiARINCWord() for i in range(numWords)]  # Creates a new array of words
                for f in range(numWords):  # Here we load data into the words
                    nwords[f].Label = f
                    nwords[f].Sdi = 1
                    nwords[f].Ssm = 2
                    nwords[f].Data = 102 + f
                    nwords[f].Parity = 1

                numWordsWritten = writers[ch].WriteScheduler(0, nwords)  # Schedule the words to the board.
                print("Updated %d scheduled words." % numWordsWritten)

    session.Stop()  # stop the sessions for reading and writing
    session.CleanUp()  # cleans up any used memory or unhandled garbage

except Exception as e:  # Catches any errors not specifically caught by the try loop.
    print("Exception: %s" % e)  # Print any errors caught.
