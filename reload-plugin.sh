#!/bin/bash

# Remove the existing tableau plugin
codex plugin remove Tableau@tableau-plugin

# Remove the plugin-codex marketplace
codex plugin marketplace remove tableau-plugin

# Add the current directory as a plugin
codex plugin marketplace add .

# Add the tableau plugin
codex plugin add Tableau@tableau-plugin