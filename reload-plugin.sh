#!/bin/bash

# Remove the existing tableau plugin
codex plugin remove tableau@plugin-codex

# Remove the plugin-codex marketplace
codex plugin marketplace remove plugin-codex

# Add the current directory as a plugin
codex plugin marketplace add .

# Add the tableau plugin
codex plugin add tableau@plugin-codex