"""Virtual accessibility must stay bounded as radio images grow."""
import importlib.util
from pathlib import Path
import types
import unittest
from unittest import mock


def load_accessibility():
    # Keep this test independent of a display server or wxPython installation,
    # without replacing wx for other modules in the test process.
    wx = types.ModuleType('wx')
    wx.Accessible = object
    wx.ACC_OK = 0
    wx.ACC_FAIL = 1
    path = (Path(__file__).parents[2] / 'chirp' / 'wxui' /
            'accessibility.py')
    spec = importlib.util.spec_from_file_location('a11y_under_test', path)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict('sys.modules', wx=wx):
        spec.loader.exec_module(module)
    return module


class TestAccessibleGrid(unittest.TestCase):
    def setUp(self):
        self.module = load_accessibility()
        self.grid = mock.Mock()
        self.grid.GetNumberCols.return_value = 17
        self.grid.GetNumberRows.return_value = 200
        self.grid.GetGridCursorRow.return_value = 9
        self.grid.GetGridCursorCol.return_value = 1
        self.grid.GetColLabelValue.return_value = 'Name'
        self.grid.GetCellValue.return_value = 'TEST010'
        self.accessible = self.module.GridAccessible(self.grid)

    def test_enumeration_does_not_scale_with_radio_size(self):
        for rows in (10, 200, 20000):
            self.grid.GetNumberRows.return_value = rows
            self.assertEqual((0, 17), self.accessible.GetChildCount())

    def test_focus_returns_native_triple_and_tracks_current_row(self):
        self.assertEqual((0, 2, None), self.accessible.GetFocus())
        self.assertEqual((0, 'TEST010'), self.accessible.GetValue(2))
        self.grid.GetCellValue.assert_called_with(9, 1)
        self.grid.GetGridCursorRow.return_value = 199
        self.accessible.GetValue(2)
        self.grid.GetCellValue.assert_called_with(199, 1)
        self.assertEqual((0, 2, None), self.accessible.GetFocus())

    def test_invalid_children_and_empty_grid(self):
        for child_id in (-1, 18):
            self.assertEqual((1, None), self.accessible.GetChild(child_id))
        self.grid.GetNumberRows.return_value = 0
        self.assertEqual((0, 0), self.accessible.GetChildCount())
        self.assertEqual((0, 0, self.accessible), self.accessible.GetFocus())

    def test_both_native_grid_surfaces_are_bounded(self):
        self.module.HAS_ACCESSIBLE = True
        self.module.wx.grid = types.SimpleNamespace(
            EVT_GRID_SELECT_CELL=object())
        accessible = self.module.attach_grid_accessible(self.grid)
        self.grid.SetAccessible.assert_called_once_with(accessible)
        window = self.grid.GetGridWindow()
        window.SetAccessible.assert_called_once_with(accessible.inner)
        self.assertEqual((0, 17), accessible.inner.GetChildCount())

    def test_property_focus_returns_native_triple(self):
        pg = mock.Mock()
        prop = object()
        pg.GetSelectedProperty.return_value = prop
        accessible = self.module.PropertyGridAccessible(pg)
        accessible._visible_props = lambda: [prop]
        self.assertEqual((0, 1, None), accessible.GetFocus())
