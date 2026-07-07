Author: Ethan Sanders

This is a web app designed to efficiently log and track data from 3D laser scanning jobs for The Wassi Group.


Proof of concept goals:
- Display each stored project and its features/information
- Create filters for projects
- Update existing projects
- Add new projects
- Delete projects
- Perform basic calculations based on filtered projects
- basic page navigation

Overall goals:
- Create a tool to efficiently document data on scan job. Should be able to be added to workflow with little additional work from scan tech.

- Avoid any areas of human error.
-- e.g. avoid using measurement tool to guesstimate the square footage of an area


Functionality Goals:

- Update/modify pre-existing data in the table. (Implemented but needs bug fixing) ***

- Anywhere that is using an "Other" category should be removed. Instead include a write-in option to create a new category and build the list of categories to choose from based on pre-existing "write-ins" in the DB.
-- E.g. A project in the data base has been labeled as "Building" so now "Building" is available in the drop down for any future project to choose. This should prevent inconsistencies in the dataset while still having the ability to
    write in new information if needed. User should prioritize finding a pre existing option before writing in their own.

- Perform basic analysis based on certain categories / filters
-- E.G. Avg # scans for Industrial Buildings over 1000sqft
-- Ideally done by toggling what filters to various features and then performing some calculation like finding the mean # of scans based on those filters.

- Create a display page to view each logged projects information.
-- Display each projects title and include a dropdown menu to display the feature information about that project, pulled from the DB/excel sheet.
-- Include edit and delete buttons to each project dropdown

- Each different Project type should collect its own set of features. This is beacause estimating the total # of scans required to complete a building will require different information than estimating the total # of scans
    for a piece of machinery.

- Create nav bar on the side to switch between different pages
-- create a template page to apply to each html page to keep consistent navigation



Data Collection:
- Project Name
-- Serves as the project ID to track projects

- Project Type
-- Choose between building, area, feature, or other.
-- The goal of this feature is to segment projects into different categories to avoid comparing the work required for scanning something like a large open field vs a building.
--- May be used to select different feature sets based on the project type

- Sector
-- Choose between commercial, industrial, residential, medical, office, other
--- This needs reworking. As is this feature is not very informative and does not fit to every project type.

- Squarefeet
-- Square footage of what was scanned. Still unsure about best practice in determining exact square footage, need more investigating ***

- # of levels/floors
-- Usually just the number of floors but may also be the number of elevation changes required to capture walls of an exterior.

- Partition Density
-- The goal of this feature is to capture how many distinct rooms/areas are in the project

- Site Condition rating (1-3)
-- Rate the amount of clutter
--- 1: No clutter e.g. Empty warehouse
--- 2: Light clutter e.g. a lived in home
--- 3: Dense clutter e.g. hoarder's house

- Interior bool
-- Was the interior included Y/N?

- Exterior bool
-- Was the exterior included Y/N?

- Roof bool
-- Was the roof included Y/N?

- % Coverage
-- What % of the square footage specified was covered
--- Sometimes rooms or sections are excluded from the scope of inaccesible

- Total # of scans
-- This data is being collected to build a model that can predict the total # of scans a job will take based on all of the previous features

- Time stamp
-- Logs when the DB was updated