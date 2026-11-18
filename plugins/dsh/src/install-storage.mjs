import {createRequire} from 'node:module';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';

/** Only installation preferences. Conversation and memory remain in DSH. */
export async function openInstallationStorage(ctx, runtimeModulesRoot) {
  const req=createRequire(join(runtimeModulesRoot,'@deepseek-ai/dsh/package.json'));
  const load=name=>import(pathToFileURL(req.resolve(name)).href);
  const [{defineDomain},{z}]=await Promise.all([load('@deepseek-ai/dsh-storage-domain'),load('zod')]);
  const domain=await ctx.storageDomain.open(defineDomain({name:'dafeiyu_installation',version:1,
    tables:{settings:{valueSchema:z.object({homeDir:z.string(),continued:z.boolean()})}}}));
  const table=domain.table('settings');
  return {read:()=>table.get('home'),save:value=>table.put('home',value),dispose:()=>domain.close()};
}
