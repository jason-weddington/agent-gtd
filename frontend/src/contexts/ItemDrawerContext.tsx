import { createContext, useContext, useState, useCallback } from 'react'
import ItemDetailDrawer from '../components/ItemDetailDrawer'
import type { Item, Project } from '../types'

interface ItemDrawerContextType {
  openItemDrawer: (item: Item, project?: Project) => void
  closeItemDrawer: () => void
}

const ItemDrawerContext = createContext<ItemDrawerContextType>({
  openItemDrawer: () => {},
  closeItemDrawer: () => {},
})

export function ItemDrawerProvider({ children }: { children: React.ReactNode }) {
  const [drawerItem, setDrawerItem] = useState<Item | null>(null)
  const [drawerProject, setDrawerProject] = useState<Project | null>(null)

  const openItemDrawer = useCallback((item: Item, project?: Project) => {
    setDrawerItem(item)
    setDrawerProject(project ?? null)
  }, [])

  const closeItemDrawer = useCallback(() => {
    setDrawerItem(null)
    setDrawerProject(null)
  }, [])

  return (
    <ItemDrawerContext.Provider value={{ openItemDrawer, closeItemDrawer }}>
      {children}
      <ItemDetailDrawer
        item={drawerItem}
        onClose={closeItemDrawer}
        onEdit={() => { closeItemDrawer() }}
        onItemUpdated={(updated) => setDrawerItem(updated)}
        projectName={drawerProject?.name}
        projectGitOrigin={drawerProject?.gitOrigin}
        projectIsOwner={drawerProject ? (drawerProject.isOwner !== false) : true}
        showAttribution={false}
      />
    </ItemDrawerContext.Provider>
  )
}

export function useItemDrawer() {
  return useContext(ItemDrawerContext)
}
