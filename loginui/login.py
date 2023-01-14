from PyQt5 import QtWidgets, uic 
from PyQt5.QtWidgets import QApplication, QDesktopWidget
from PyQt5.QtGui import QImage, QPixmap 
from PyQt5.QtCore import QCoreApplication, Qt, QPoint
import sys,os 


class Ui(QtWidgets.QMainWindow):
    def __init__(self):
        super(Ui, self).__init__()
        self.path = os.path.dirname(os.path.abspath(__file__))
        self.ui = uic.loadUi(self.path+'/style/login.ui', self)
        _translate = QCoreApplication.translate
        self.setWindowTitle(_translate("Form", "PY LOGİN Style")) 
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.ui.pushButton_2.clicked.connect(self.close)
        self.center()
        self.oldPos = self.pos()
        self.isMoveApp = False
        self.show()

    def center(self):
        qr = self.frameGeometry()
        cp = QDesktopWidget().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())
        pos = qr.topLeft()
        self.topLabelPos = [pos.x(), pos.y(), pos.x()+360, pos.y()+48] 
    def mousePressEvent(self, event):
        self.isMoveApp = False
        self.oldPos = event.globalPos() 
        x, y = self.oldPos.x(), self.oldPos.y()
        if x > self.topLabelPos[0] and x < self.topLabelPos[2]:
            if y > self.topLabelPos[1] and y < self.topLabelPos[3]:
                self.isMoveApp = True 
    def mouseMoveEvent(self, event):
        if self.isMoveApp:
            delta = QPoint(event.globalPos() - self.oldPos)
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = event.globalPos()
            x, y = self.topLabelPos[0] + \
                delta.x(), self.topLabelPos[1] + delta.y()
            self.topLabelPos = [x, y, x+720, y+48]
    


if __name__ == '__main__':
    app = QApplication(sys.argv)
    mainWindow = Ui()
    mainWindow.show()
    sys.exit(app.exec_())
