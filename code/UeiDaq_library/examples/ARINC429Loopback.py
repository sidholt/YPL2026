import UeiDaq
import time
#   Python Implementation of a loopback read/write ARINC Test
#   Uses customized versions of C++ read and write functions
#
#   When reading the words back from the board, they are returned in a 2d array.
#   ex.     returnWords [word index][word data]
#   Where the word data is stored as
#                   [0] -> Label
#                   [1] -> Data
#                   [2] -> Sdi
#                   [3] -> Ssm
#                   [4] -> Parity
#

numWords = 12  # this is where we set the size of the word buffer to be sent

try:
    session = UeiDaq.CUeiSession()

    # Be sure to update the bits/sec, parity, and SDI to match the settings for your board
    session.CreateARINCInputPort("pdna://192.168.100.12/dev4/arx6",
                                 UeiDaq.UeiARINCBitsPerSecond12500,
                                 UeiDaq.UeiARINCParityOdd,
                                 False,
                                 0)
    inputPorts = session.GetNumberOfChannels()  # read input ports so we know what arinc board we're dealin with.

    session.CreateARINCOutputPort("pdna://192.168.100.12/dev4/atx0",
                                  UeiDaq.UeiARINCBitsPerSecond12500,
                                  UeiDaq.UeiARINCParityOdd)

    outputPorts = session.GetNumberOfChannels() - inputPorts

    session.ConfigureTimingForMessagingIO(1, 0)  # configure session for IO messaging

    session.GetTiming().SetTimeout(1000)

    readers = [UeiDaq.CUeiARINCReader(session.GetDataStream()) for i in range(inputPorts)]
    for ch in range(inputPorts):  # Create readers for every input port
        readers[ch] = UeiDaq.CUeiARINCReader(session.GetDataStream(), session.GetChannel(ch).GetIndex())

    writers = [UeiDaq.CUeiARINCWriter(session.GetDataStream()) for i in range(outputPorts)]  # create list of writers to write to
    for ch in range(outputPorts):  # Create writers for every output port
        writers[ch] = UeiDaq.CUeiARINCWriter(session.GetDataStream(), session.GetChannel(inputPorts + ch).GetIndex())

    words = [UeiDaq.tUeiARINCWord() for i in range(numWords)]  # create list of ARINC words to hold data we want to send

    session.Start()  # Start the session

    for i in range(20):  # write and read 100 times
        for ch in range(outputPorts):  # for each output port, we want to write the words to the stream
            numWordsWritten = 0
            port = session.GetChannel(inputPorts + ch).GetIndex()
            for f in range(numWords):  # Here we load data into the words
                words[f].Label = (i % 100) + ch
                words[f].Sdi = 1
                words[f].Ssm = 2
                words[f].Data = f
                words[f].Parity = 0
                #  words.Parity is not filled, as it is set default when created
            numWordsWritten = writers[ch].Write(words)  # Number of words written is returned when write is successful

            print("TX Port %d: Wrote %d words." % (port, numWordsWritten))
        time.sleep(0.2)
        for ch in range(inputPorts):  # read from each input channel
            port = session.GetChannel(ch).GetIndex()

            try:  # because we're reading and waiting from data, we have to catch a timeout error
                returnWords = readers[ch].Read(numWords)  # word array is returned by .Read, see header comment
                # for details about accessing the data inside
            except Exception as e:
                if e.args[0] == UeiDaq.UEIDAQ_TIMEOUT_ERROR:
                    continue
                raise  # rethrow any other exceptions if it wasn't a timeout error
            numWordsRead = len(returnWords)
            print("RX port %d: Received %d words" % (port, numWordsRead))
            for v in range(numWordsRead):  # prints the word data received
                print ("RX port %d: Received word: Label=%d Data=%d Sdi=%d Ssm=%d Parity=%d" % (
                    port, returnWords[v].Label, returnWords[v].Data, returnWords[v].Sdi, returnWords[v].Ssm,
                    returnWords[v].Parity))

    session.Stop()  # stop the sessions for reading and writing
    session.CleanUp()  # cleans up any used memory or unhandled garbage

except Exception as e:  # catch any exception thrown by the python function calls and prints the error trace
    print("Exception %s" % e)
