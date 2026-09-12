from __future__ import annotations
from pathlib import Path
from typing import override
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QCloseEvent, QFontMetrics
from PySide6.QtWidgets import QComboBox,QDialog,QLabel,QMessageBox,QProgressBar,QVBoxLayout,QWidget
from tagger.domain.models import ImageEntry
from tagger.image_processing import convert_image
from tagger.ui.dialogs.transparency import TransparencySelectionDialog
class ImageTransformDialog(TransparencySelectionDialog):
 def __init__(self,entries:list[ImageEntry],parent:QWidget|None=None,*,root_directory:Path|None=None)->None:
  super().__init__(entries,parent,root_directory=root_directory); self.setWindowTitle('Convert Images'); self.remove_button.setText('Convert'); self.format_combo=QComboBox(self); self.format_combo.addItems(['PNG','JPEG','WEBP']); self.layout().insertWidget(2,QLabel('Target format:')); self.layout().insertWidget(3,self.format_combo); self.remove_button.clicked.disconnect(); self.remove_button.clicked.connect(self._accept_selection); self.converted_paths=[]
 def _accept_selection(self)->None:
  paths=self.selected_paths; target=self.format_combo.currentText().lower(); target='jpg' if target=='jpeg' else target; candidates=[p for p in paths if p.suffix.lower().lstrip('.')!=target]; destinations=[p.with_suffix('.'+target) for p in candidates]; seen=set(); conflicts=[]
  for destination in destinations:
   if destination.exists() or destination in seen: conflicts.append(destination)
   seen.add(destination)
  if conflicts: QMessageBox.warning(self,'Conversion Conflict','The following files already exist:\n'+'\n'.join(p.name for p in conflicts)); return
  if target=='jpg':
   from tagger.image_processing import image_has_alpha
   if any(image_has_alpha(p) for p in candidates) and QMessageBox.question(self,'JPEG Transparency','JPEG cannot preserve transparency. Continue?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
  self.selected_paths_for_conversion=candidates; self.target_format=target; self.accept()
class _Signals(QObject):
 progress=Signal(int,int,str); completed=Signal(object)
class _Worker(QRunnable):
 def __init__(self,paths,target): super().__init__(); self.paths=paths; self.target=target; self.signals=_Signals()
 @override
 def run(self):
  done=[]; failures=[]
  for i,p in enumerate(self.paths,1):
   self.signals.progress.emit(i-1,len(self.paths),p.name)
   try: done.append(convert_image(p,self.target) or p)
   except (OSError,ValueError) as e: failures.append(f'{p.name}: {e}')
   self.signals.progress.emit(i,len(self.paths),p.name)
  self.signals.completed.emit((done,failures))
class ConvertProgressDialog(QDialog):
 completed=Signal(object)
 def __init__(self,paths,target,parent=None):
  super().__init__(parent); self.setWindowTitle('Converting Images'); self.setWindowModality(Qt.WindowModality.WindowModal); self.setFixedWidth(640); self.label=QLabel('Preparing images...'); self.label.setMinimumWidth(600); self.progress=QProgressBar(); self.progress.setRange(0,len(paths)); l=QVBoxLayout(self); l.addWidget(self.label); l.addWidget(self.progress); self._running=False; self._worker=_Worker(paths,target); self._worker.signals.progress.connect(self._update); self._worker.signals.completed.connect(self._complete)
 def start(self): self._running=True; QThreadPool.globalInstance().start(self._worker)
 def _update(self,d,t,n):
  self.progress.setRange(0,t); self.progress.setValue(d); self.label.setToolTip(n); self.label.setText(QFontMetrics(self.label.font()).elidedText(n, Qt.TextElideMode.ElideMiddle, self.label.width()))
 def _complete(self,r): self._running=False; self.completed.emit(r); self.accept()
 def reject(self):
  if not self._running: super().reject()
 @override
 def closeEvent(self,e:QCloseEvent):
  if self._running:e.ignore()
  else:super().closeEvent(e)
