/* =========================================================================
   Plantilla de seguridad a nivel de fila (RLS) para la fase multiusuario.
   NO ejecutar tal cual: revisar nombres, esquema y política de negocio.
   ========================================================================= */

/* 1) Configuración aplicada: qué ve cada usuario.
      Es la tabla que leerá src/scope.py (TODO en resolver_alcance).
      Añadir un usuario o cambiar su alcance = INSERT/DELETE, sin tocar código. */
IF SCHEMA_ID('seguridad') IS NULL EXEC('CREATE SCHEMA seguridad');
GO

CREATE TABLE seguridad.UsuarioAlcance
(
    Usuario   sysname       NOT NULL,
    Dimension sysname       NOT NULL,   -- 'Sucursal', 'Empresa', 'Vendedor'...
    Valor     nvarchar(200) NOT NULL,
    Activo    bit           NOT NULL CONSTRAINT DF_UsuarioAlcance_Activo DEFAULT (1),
    CONSTRAINT PK_UsuarioAlcance PRIMARY KEY (Usuario, Dimension, Valor)
);
GO

/* 2) Función de predicado: el MOTOR decide qué filas existen para el usuario.
      Con RLS, aunque la aplicación tenga un bug y no filtre, SQL Server filtra. */
CREATE OR ALTER FUNCTION seguridad.fn_AlcanceSucursal(@Sucursal sysname)
RETURNS TABLE
WITH SCHEMABINDING
AS
RETURN
(
    SELECT 1 AS Visible
    WHERE
        -- Sin configuración => alcance total (ajustar a la política real:
        -- en entornos sensibles conviene lo contrario, "sin config = sin acceso").
        NOT EXISTS (SELECT 1 FROM seguridad.UsuarioAlcance
                    WHERE Usuario = CAST(SESSION_CONTEXT(N'usuario_app') AS sysname) AND Activo = 1)
        OR EXISTS (SELECT 1 FROM seguridad.UsuarioAlcance
                   WHERE Usuario = CAST(SESSION_CONTEXT(N'usuario_app') AS sysname)
                     AND Dimension = N'Sucursal' AND Valor = @Sucursal AND Activo = 1)
);
GO

/* 3) Política: se aplica sobre la tabla de hechos. */
CREATE SECURITY POLICY seguridad.PoliticaAlcance
ADD FILTER PREDICATE seguridad.fn_AlcanceSucursal(Sucursal) ON dbo.Ventas
WITH (STATE = ON);
GO

/* 4) La aplicación declara quién es al abrir la conexión.
      OJO: SESSION_CONTEXT lo fija la propia aplicación, así que es una barrera
      contra bugs de la app, no contra un atacante que controla la conexión.
      Para defensa real de extremo a extremo, usar autenticación por usuario
      (Microsoft Entra ID o usuarios contenidos por persona) y SUSER_SNAME().
      Ver el README, sección "Modelo de seguridad". */
EXEC sys.sp_set_session_context @key = N'usuario_app', @value = N'juan.perez';
GO

/* 5) Comprobación rápida: el login de la aplicación necesita poder leer la
      configuración, pero no modificarla. */
-- GRANT SELECT ON seguridad.UsuarioAlcance TO [app_reportes];
-- GRANT SELECT ON SCHEMA::dbo TO [app_reportes];
-- DENY INSERT, UPDATE, DELETE ON SCHEMA::dbo TO [app_reportes];
