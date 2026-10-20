import { AllCommunityModule, ModuleRegistry, themeQuartz } from 'ag-grid-community'

ModuleRegistry.registerModules([AllCommunityModule])

export const gkGridTheme = themeQuartz.withParams({
  backgroundColor: '#121722',
  foregroundColor: '#e7eaf2',
  headerBackgroundColor: '#171d2b',
  headerTextColor: '#8b93a7',
  oddRowBackgroundColor: 'rgba(23, 29, 43, 0.5)',
  borderColor: '#262e40',
  accentColor: '#7c6cf6',
  rowHoverColor: 'rgba(124, 108, 246, 0.12)',
  wrapperBorderRadius: 12,
  fontFamily: 'inherit',
  fontSize: 13,
})
