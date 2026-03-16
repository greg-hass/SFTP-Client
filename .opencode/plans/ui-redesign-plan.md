# SFTP Client UI Redesign Plan

## User Requirements
1. **Density**: Medium (balanced visibility)
2. **Visual Style**: Subtle depth (light shadows, clean separation)
3. **Navigation**: Breadcrumbs + path bar (both)
4. **File List**: Recommendation - **Table view** (columns) as default, icon view optional
5. **Color Scheme**: Darker/more neutral (VS Code inspired)

## Design Philosophy
Transform from "card-centric glassmorphism" to "modern professional file manager" like:
- VS Code Explorer (clean, dense, professional)
- Linear (minimalist, modern)
- macOS Finder (balanced usability)
- GitHub's interface (dark, clean, information-rich)

## Key Transformations

### 1. Color Scheme (Darker/Neutral)
**Current**: #09111f with lime (#b7f36f) and cyan (#78d6f3) accents
**New**:
- Background: #0d1117 (GitHub dark)
- Secondary: #161b22
- Borders: #30363d (subtle separation)
- Primary accent: #58a6ff (blue - professional, familiar)
- Text: #e6edf3 (primary), #8b949e (secondary)

### 2. Layout Structure
**Current**: 320px sidebar with massive cards, hero section, 4 metric cards
**New**:
- **Compact sidebar**: 240px, clean bookmark list (no cards)
- **Clean header bar**: 48px height, breadcrumbs + path + actions
- **Professional file table**: Column headers, dense rows (36px height)
- **Status bar**: Bottom, minimal, contextual info
- **No hero section**: Information density over marketing

### 3. File List Style
**Recommendation: Table view with columns**

**Why table over grid?**
- Professional file managers (Finder, Explorer, ForkLift) default to list/table
- More information density (Name, Size, Modified, Type, Permissions visible)
- Easier keyboard navigation (arrow keys)
- Better for large directories
- Sortable columns

**Columns**:
- Icon (20px)
- Name (flexible width)
- Size (100px)
- Modified (160px)
- Type (100px)
- Permissions (120px)

**Optional**: Toggle to icon/grid view for image folders

### 4. Navigation
**Breadcrumbs + Path bar combination**:
- Breadcrumbs show clickable path segments (Home > Folder > Subfolder)
- Last segment or adjacent area is editable path input
- Click breadcrumb = navigate there
- Type in path = jump directly

### 5. Visual Hierarchy
- **Flat surfaces**: No heavy glassmorphism, no blur backdrops
- **Subtle depth**: Light shadows (0 1px 2px) for elevation
- **Clean borders**: 1px solid separators
- **Medium density**: Balanced padding (12px-16px)
- **Typography**: 13px base, clear hierarchy

### 6. Sidebar (Bookmarks)
**Current**: Chunky cards with gradients, 52px icons
**New**:
- Clean list view
- 20px icons, compact rows
- Hover highlight (no card containers)
- Quick connect button in header
- Divider between sections

### 7. Interactions
- **Keyboard shortcuts**: Cmd/Ctrl+K (search), arrow navigation, Enter to open
- **Context menus**: Right-click on files
- **Drag & drop**: Visual feedback (blue highlight, dashed border)
- **Selection**: Blue background highlight, keyboard navigable
- **Hover states**: Subtle background change

### 8. Dual Pane Mode
**Current**: Large transfer buttons, card containers
**New**:
- Two panes side by side
- Minimal transfer buttons between (arrows)
- Active pane highlighted with border
- Each pane has its own breadcrumb/path

## Implementation Steps

### Phase 1: Core Structure
1. Update CSS variables (colors, spacing, shadows)
2. Redesign layout grid (sidebar + header + main)
3. Implement clean header with breadcrumbs
4. Create table-based file list

### Phase 2: Components
5. Redesign sidebar with compact bookmarks
6. Update buttons and form elements
7. Implement modals (clean overlay style)
8. Add context menus

### Phase 3: Interactions
9. Keyboard navigation
10. Selection and multi-select
11. Drag and drop visuals
12. Toast notifications

### Phase 4: Polish
13. View toggle (list/table/grid)
14. Column sorting
15. Responsive breakpoints
16. Animation refinements

## Visual Reference

### Before (Current)
- Heavy cards with 28px radius
- Glassmorphism blur effects
- Multiple gradient backgrounds
- Hero section with large text
- 4 separate metric cards
- Chunky bookmark cards

### After (New)
- Flat panels with 6-8px radius
- Subtle 1px borders
- Single dark background
- Compact header bar
- Single status bar
- List-based bookmarks
- Table file view with headers

## File Changes Required
1. `app/templates/index.html` - Complete rewrite of HTML structure
2. `app/static/style.css` - New CSS design system
3. JavaScript updates for:
   - Table rendering
   - Keyboard navigation
   - Column sorting
   - View toggling

## Success Criteria
- [ ] Looks like a professional native file manager
- [ ] No "card" aesthetic remaining
- [ ] Clean, modern appearance
- [ ] Efficient space usage
- [ ] Smooth interactions
- [ ] Keyboard accessible
- [ ] Responsive on smaller screens
