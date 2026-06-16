"use client";

import { useRouter } from "next/navigation";

import { useComposer } from "@/app/model/store/composer-store";
import { routes } from "@/shared/lib/routes";
import { Composer } from "@/widgets/composer";
import { PageHeader } from "@/widgets/page-header";

export function HomeScreen() {
  const router = useRouter();
  const { sendHome } = useComposer();

  return (
    <>
      <PageHeader
        left={
          <button
            className="page-header-home-brand"
            type="button"
            onClick={() => router.push(routes.home())}
          >
            TG Platform
          </button>
        }
      />
      <div className="home-layout">
        <div className="home-intro">
          <h3>Над чем работаем?</h3>
        </div>
        <Composer scope="home" onSubmit={sendHome} />
      </div>
    </>
  );
}
