from PyQt5 import QtWidgets, uic 
from PyQt5.QtWidgets import QApplication 
from PyQt5.QtGui import QImage
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import QTimer, QCoreApplication
import sys,os,cv2


class Ui(QtWidgets.QMainWindow):
    def __init__(self): 
        super(Ui, self).__init__()
        self.path = os.path.dirname(os.path.abspath(__file__))
        self.ui = uic.loadUi(self.path+'/cam.ui', self)
        _translate = QCoreApplication.translate
        self.setWindowTitle(_translate("Form", "PyQT5 | Cv2 - Cam viewer")) 
        self.timer = QTimer() 
        self.timer.timeout.connect(self.viewCam) 
        self.ui.pushButton.clicked.connect(self.controlTimer)
        self.show()  

    def viewCam(self): 
        # Cam Read
        ret, image = self.cap.read() 
        # Image Resize
        stretch_near = cv2.resize(image, (360, 240), interpolation=cv2.INTER_LINEAR)
        # color Type Change
        image = cv2.cvtColor(stretch_near, cv2.COLOR_BGR2RGB)
        height, width, channel = image.shape
        step = channel * width 
        qImg = QImage(image.data, width, height, step, QImage.Format_RGB888) 
        self.ui.label.setPixmap(QPixmap.fromImage(qImg))

    def controlTimer(self): 
        if not self.timer.isActive(): 
            self.cap = cv2.VideoCapture(0) 
            self.timer.start(20) 
            self.ui.pushButton.setText("Stop")
        else: 
            self.timer.stop() 
            self.cap.release() 
            self.ui.pushButton.setText("Start")
  
if __name__ == '__main__':
    app = QApplication(sys.argv) 
    mainWindow = Ui()
    mainWindow.show() 
    sys.exit(app.exec_())
