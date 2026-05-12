import UeiDaq
import numpy
import wx
import wx.lib.plot as plot
import wx.lib.colourdb as colourdb

class TestPanel(wx.Panel):
    def __init__(self, parent):
        wx.Panel.__init__(self, parent)
        
        self.wavePlotCanvas = plot.PlotCanvas(self)
        self.wavePlotCanvas.SetEnableLegend(True)
        self.wavePlotCanvas.SetEnableZoom(True)
        
        self.fftPlotCanvas = plot.PlotCanvas(self)
        self.fftPlotCanvas.SetEnableLegend(True)
        self.fftPlotCanvas.SetEnableZoom(True)
                
        self.startButton = wx.Button(self, label="Start")
        self.startButton.Bind(wx.EVT_BUTTON, self.onStart)
        
        self.stopButton = wx.Button(self, label="Stop")
        self.stopButton.Bind(wx.EVT_BUTTON, self.onStop)
        self.stopButton.Enable(False)
        
        self.output = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY |wx.HSCROLL)
        
        self.buttonBox = wx.BoxSizer(wx.HORIZONTAL)
        self.buttonBox.Add(self.startButton, flag=wx.EXPAND|wx.ALL, border=5)
        self.buttonBox.Add(self.stopButton, flag=wx.EXPAND|wx.ALL, border=5)
        
        self.parametersBox = wx.FlexGridSizer(cols=2, hgap=5, vgap=5) 
        self.parametersBox.Add(wx.StaticText(self, label="Resource"), border=0)
        self.resource = wx.TextCtrl(self, value="simu://dev0/AI0:7")
        self.parametersBox.Add(self.resource,  border=0)
        self.parametersBox.Add(wx.StaticText(self, label="Number of scans"), border=0)
        self.numScans = wx.TextCtrl(self, value="100")
        self.parametersBox.Add(self.numScans,  border=0)
        self.parametersBox.Add(wx.StaticText(self, label="Rate"), border=0)
        self.rate = wx.TextCtrl(self, value="1000")
        self.parametersBox.Add(self.rate, border=0)
                         
        self.vbox = wx.BoxSizer(wx.VERTICAL)
        self.vbox.Add(self.wavePlotCanvas, proportion=1, flag=wx.EXPAND|wx.ALL, border=5)
        self.vbox.Add(self.fftPlotCanvas, proportion=1, flag=wx.EXPAND|wx.ALL, border=5)
        self.vbox.Add(self.parametersBox, flag=wx.EXPAND|wx.ALL, border=5)
        self.vbox.Add(self.buttonBox, flag=wx.EXPAND|wx.ALL, border=5)
        self.vbox.Add(self.output, proportion=0, flag=wx.EXPAND|wx.ALL, border=5)
        
        self.SetSizer(self.vbox)   
        
        # Set the timer to generate events to us
        timerId = wx.NewId()
        self.timer = wx.Timer(self, timerId)
        self.Bind(wx.EVT_TIMER, self.onTimer, id=timerId) 
        
        self.colours = [ "blue", "red", "green", "black", "yellow", "purple", "orange", "brown"]
        self.scanCounter = 0
        self.bufferSize = 100
        
    def onStart(self, event):
        numScans = int(self.numScans.GetValue())
        rate = float(self.rate.GetValue())
        try:
            self.session = UeiDaq.CUeiSession()
        
            self.session.CreateAIChannel(str(self.resource.GetValue()), -10.0, 10.0, UeiDaq.UeiAIChannelInputModeSingleEnded)
            self.session.ConfigureTimingForBufferedIO(numScans, UeiDaq.UeiTimingClockSourceInternal, rate, UeiDaq.UeiDigitalEdgeRising, UeiDaq.UeiTimingDurationContinuous)
        
            self.reader = UeiDaq.CUeiAnalogScaledReader(self.session.GetDataStream())
        
            self.session.Start()
        except Exception as e:
            print(e)
            
        self.xbuffer = numpy.arange(0.0, numScans, 1.0)
        self.ybuffer = numpy.zeros((numScans, self.session.GetNumberOfChannels()))
        
        
        self.timer.Start(50.0, wx.TIMER_CONTINUOUS)
        
        self.startButton.Enable(False)
        self.stopButton.Enable(True)
        
    def onStop(self, event):
        self.timer.Stop()
        try:
            self.session.Stop()
            self.session.CleanUp()
        except Exception as e:
            print(e)
            
        self.startButton.Enable(True)
        self.stopButton.Enable(False)
        
    def outputLog(self, message):
        self.output.AppendText(message.strip('\r'))
        self.output.ShowPosition(self.output.GetLastPosition())
        self.output.Refresh()
        self.output.Update()
        
    def onTimer(self, event):
        lines = []
        fftLines = []
        
        try:    
            numScans = self.session.GetDataStream().GetNumberOfScans()
            
            self.reader.ReadMultipleScans(self.ybuffer)
            
            for ch in range(0,self.session.GetNumberOfChannels()):
                color = self.colours[ch%len(self.colours)]
                lines.append(plot.PolyLine(numpy.transpose([self.xbuffer, self.ybuffer[:,ch]]), legend='Ch %d' % ch, colour=color, width=1))
                
                waveForm = self.ybuffer[:,ch]
                fft = numpy.abs(numpy.fft.fft(waveForm))
                fftLines.append(plot.PolyLine(numpy.transpose([self.xbuffer[0:numScans/2], fft[0:numScans/2]]), legend='Ch %d' % ch, colour=color, width=1))
                
            gc = plot.PlotGraphics(lines, 'Graph', 'Sample', 'Amplitude')
            self.wavePlotCanvas.Draw(gc,xAxis=None, yAxis=None)
            
            gc = plot.PlotGraphics(fftLines, 'FFT', 'Sample', 'Amplitude')
            self.fftPlotCanvas.Draw(gc,xAxis=None, yAxis=None)
        except Exception as e:
            print(e)     
        
class TestFrame(wx.Frame):
    def __init__(self, parent, ID, title, size):
        wx.Frame.__init__(self, parent, ID, title, wx.DefaultPosition, size)
        self.bkg = TestPanel(self) 
        
if __name__ == "__main__":    
    class TestApp(wx.App):
        def OnInit(self):
            win = TestFrame(parent=None, ID=-1, title="MUeiDaq test Panel", size=(600, 600))
            win.Show(True)
            return True
        
    app = TestApp(0)     
    app.MainLoop()

