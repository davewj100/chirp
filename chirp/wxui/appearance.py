"""Application appearance, selected before any native windows are created."""
import logging
import sys

import wx

LOG = logging.getLogger(__name__)
MODES = ('system', 'light', 'dark')


def selected_mode(conf):
    mode = conf.get('appearance', 'prefs') or 'system'
    return mode if mode in MODES else 'system'


def initialize(app, conf):
    mode = selected_mode(conf)
    if hasattr(app, 'SetAppearance'):
        choice = getattr(wx.App.Appearance, mode.title())
        result = app.SetAppearance(choice)
        LOG.info('Application appearance %s: %s', mode, result)
    elif sys.platform == 'win32' and mode != 'light':
        LOG.warning('Windows dark appearance requires wxPython 4.3 or later; '
                    'using light appearance')


def style_grid(grid):
    """Use native palette for the custom channel table too."""
    colour = wx.SystemSettings.GetColour
    grid.SetDefaultCellBackgroundColour(colour(wx.SYS_COLOUR_WINDOW))
    grid.SetDefaultCellTextColour(colour(wx.SYS_COLOUR_WINDOWTEXT))
    grid.SetLabelBackgroundColour(colour(wx.SYS_COLOUR_BTNFACE))
    grid.SetLabelTextColour(colour(wx.SYS_COLOUR_BTNTEXT))
    grid.SetSelectionBackground(colour(wx.SYS_COLOUR_HIGHLIGHT))
    grid.SetSelectionForeground(colour(wx.SYS_COLOUR_HIGHLIGHTTEXT))
    grid.SetGridLineColour(colour(wx.SYS_COLOUR_3DLIGHT))


def is_dark():
    return (hasattr(wx.SystemSettings, 'GetAppearance') and
            wx.SystemSettings.GetAppearance().IsDark())


def style_property_grid(grid):
    # Native disabled grey is too dim against the Windows dark background.
    if is_dark():
        grid.SetCellDisabledTextColour(wx.Colour(170, 170, 170))


def immutable_background():
    if is_dark():
        return wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE)
    return wx.Colour(245, 245, 245)
