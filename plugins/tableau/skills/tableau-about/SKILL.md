---
name: tableau-about
description: Explain what the Tableau plugin is for and how it helps users work with existing or new Tableau content. Use when someone asks about the plugin, its purpose, suitable use cases, or why they should use it.
---

# Tableau Plugin Overview

Explain the Tableau plugin in terms of the outcomes it enables. Do not present an inventory of tools, APIs, or low-level functionality.

Focus on two primary uses.

## Surface and understand existing content

The plugin helps users find dashboards and workbooks that already exist on their Tableau site and understand what that content is showing.

Users can ask the plugin to:

- Find relevant dashboards or workbooks.
- Explain charts, dashboards, trends, and notable results.
- Investigate a subset of items in a dense visualization.
- Identify items that meet particular criteria.
- Compare selected items or categories.
- Summarize important patterns and findings.

For example, if a dashboard contains a chart with more than 100 items, the user can ask which items satisfy a condition or request more detail about a particular subset.

Note: the plugin does not have direct access to the underlying data from a visual, only the summary data.  So any summaries/explanations are based on what is visible in the dashboards

## Author new content

The plugin helps users create new Tableau content either from a blank workbook or by using an existing workbook as a starting point.

The model generates the requested workbook on the fly and publishes the new or updated result to Tableau Cloud. Users can describe the analysis, visualization, dashboard, filters, or changes they want without needing to understand Tableau workbook internals.

## Response guidance

When describing the plugin:

- Lead with the two primary uses above.
- Emphasize discovery, explanation, investigation, creation, iteration, and publishing.
- Describe benefits and user outcomes rather than underlying tools.
- Do not mention XML unless the user explicitly asks how workbook generation works internally.
- If implementation details are requested, explain that the model constructs the workbook definition programmatically.
- Do not imply that customers need to understand workbook XML or edit it themselves.
- Include a few representative example requests when helpful.

For a general question such as “What can the Tableau plugin do?”, provide a concise explanation of both primary uses and finish with examples of what the user could ask.